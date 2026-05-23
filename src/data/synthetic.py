"""Deterministic sample data for public, reproducible notebooks."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def generate_underlying_series(
    symbol: str = "SPY",
    *,
    start: str = "2023-01-03",
    periods: int = 320,
    seed: int = 7,
) -> pd.DataFrame:
    """Create a deterministic EOD underlying path with volatility regimes."""

    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=periods)
    regime = np.where(np.arange(periods) < periods * 0.55, 0.011, 0.018)
    drift = np.where(np.arange(periods) % 53 < 29, 0.00035, -0.00005)
    shocks = rng.normal(drift, regime)
    shocks[::61] -= 0.035
    close = 420.0 * np.exp(np.cumsum(shocks))
    returns = pd.Series(close, index=dates).pct_change().fillna(0.0)
    realized_vol_21d = returns.rolling(21, min_periods=5).std().fillna(returns.std()) * np.sqrt(252)
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "close": close.round(4),
            "return": returns.to_numpy(),
            "realized_vol_21d": realized_vol_21d.to_numpy(),
            "source": "deterministic_synthetic",
            "is_synthetic": True,
        }
    )


def generate_synthetic_chain(
    *,
    as_of: str | pd.Timestamp = "2024-04-19",
    symbol: str = "SPY",
    spot: float = 500.0,
    seed: int = 11,
    expiries_days: tuple[int, ...] = (7, 14, 30, 60),
    moneyness_grid: tuple[float, ...] = (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15),
) -> pd.DataFrame:
    """Generate a small option chain with smile, skew, volume, and OI fields."""

    from options_pipeline.pricing import black_scholes_price

    rng = np.random.default_rng(seed)
    as_of_ts = pd.Timestamp(as_of)
    rows: list[dict[str, object]] = []
    for dte in expiries_days:
        expiry = as_of_ts + pd.offsets.BDay(dte)
        tau = max(dte / 252.0, 1.0 / 252.0)
        term = 0.02 * np.log1p(dte / 30.0)
        for moneyness in moneyness_grid:
            strike = round(spot * moneyness, 2)
            smile = 0.30 * (np.log(moneyness) ** 2)
            for option_type in ("C", "P"):
                put_skew = 0.035 * max(1.0 - moneyness, 0.0) if option_type == "P" else 0.0
                iv = float(np.clip(0.18 + term + smile + put_skew, 0.07, 0.75))
                theo = black_scholes_price(spot, strike, 0.04, iv, tau, option_type)
                spread = max(0.02, theo * (0.015 + 0.02 * abs(moneyness - 1.0)))
                micro_noise = rng.normal(0.0, spread * 0.08)
                mid = max(0.01, theo + micro_noise)
                bid = max(0.0, mid - spread / 2.0)
                ask = mid + spread / 2.0
                liquidity_shape = np.exp(-abs(np.log(moneyness)) * 8.0) * np.exp(-dte / 90.0)
                volume = int(max(1, rng.poisson(70 * liquidity_shape + 3)))
                open_interest = int(max(5, rng.poisson(500 * liquidity_shape + 20)))
                rows.append(
                    {
                        "as_of": as_of_ts.date().isoformat(),
                        "symbol": symbol,
                        "expiry": pd.Timestamp(expiry).date().isoformat(),
                        "option_type": option_type,
                        "strike": strike,
                        "spot": float(spot),
                        "bid": round(float(bid), 4),
                        "ask": round(float(ask), 4),
                        "mid": round(float((bid + ask) / 2.0), 4),
                        "iv": round(iv, 6),
                        "volume": volume,
                        "open_interest": open_interest,
                        "source": "deterministic_synthetic",
                        "is_synthetic": True,
                    }
                )
    return pd.DataFrame(rows)


def write_sample_snapshot(path: str | Path, *, seed: int = 11) -> Path:
    """Write the deterministic option sample used by docs and notebooks."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    generate_synthetic_chain(seed=seed).to_csv(path, index=False)
    return path

