"""A compact, auditable discrete-time market-making simulator.

The simulator is not a live execution engine.  It is a research harness for
testing quote policies, inventory limits, fill assumptions, and PnL attribution
under deterministic seeds.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np
import pandas as pd

from options_pipeline.risk import compute_risk_metrics


@dataclass(frozen=True)
class MarketMakingConfig:
    """Configuration for the discrete-time simulator."""

    steps: int = 1_000
    seed: int = 17
    initial_mid: float = 100.0
    dt: float = 1.0 / 390.0
    volatility: float = 0.018
    drift: float = 0.0
    base_half_spread_bps: float = 3.0
    inventory_aversion_bps: float = 0.8
    adverse_selection_bps: float = 0.6
    max_inventory: int = 25
    order_size: int = 1
    fee_per_contract: float = 0.005
    fill_intensity: float = 0.34


@dataclass(frozen=True)
class SimulationResult:
    """Simulator output with event-level path and summary metrics."""

    path: pd.DataFrame
    metrics: dict[str, float]
    config: MarketMakingConfig


def _fill_probability(distance_bps: float, inventory_penalty: float, intensity: float) -> float:
    raw = intensity * np.exp(-max(distance_bps, 0.0) / 5.0) * np.exp(-inventory_penalty)
    return float(np.clip(raw, 0.0, 0.95))


def run_market_making_simulation(config: MarketMakingConfig | None = None) -> SimulationResult:
    """Run a seeded discrete-time market-making simulation."""

    cfg = config or MarketMakingConfig()
    rng = np.random.default_rng(cfg.seed)
    mid = cfg.initial_mid
    cash = 0.0
    inventory = 0
    rows: list[dict[str, float | int]] = []
    prev_equity = 0.0
    for step in range(cfg.steps):
        shock = rng.normal(cfg.drift * cfg.dt, cfg.volatility * np.sqrt(cfg.dt))
        mid = max(0.01, mid * np.exp(shock))
        inventory_skew_bps = cfg.inventory_aversion_bps * inventory
        half_spread = (cfg.base_half_spread_bps + cfg.adverse_selection_bps * abs(shock) * 10_000.0) / 10_000.0 * mid
        bid = mid - half_spread - inventory_skew_bps / 10_000.0 * mid
        ask = mid + half_spread - inventory_skew_bps / 10_000.0 * mid
        bid_fill = False
        ask_fill = False
        if inventory < cfg.max_inventory:
            bid_fill = rng.random() < _fill_probability(cfg.base_half_spread_bps, max(inventory, 0) / cfg.max_inventory, cfg.fill_intensity)
        if inventory > -cfg.max_inventory:
            ask_fill = rng.random() < _fill_probability(cfg.base_half_spread_bps, max(-inventory, 0) / cfg.max_inventory, cfg.fill_intensity)
        if bid_fill:
            inventory += cfg.order_size
            cash -= bid * cfg.order_size + cfg.fee_per_contract
        if ask_fill:
            inventory -= cfg.order_size
            cash += ask * cfg.order_size - cfg.fee_per_contract
        equity = cash + inventory * mid
        pnl = equity - prev_equity
        prev_equity = equity
        rows.append(
            {
                "step": step,
                "mid": mid,
                "bid": bid,
                "ask": ask,
                "inventory": inventory,
                "cash": cash,
                "equity": equity,
                "pnl": pnl,
                "bid_fill": int(bid_fill),
                "ask_fill": int(ask_fill),
            }
        )
    path = pd.DataFrame(rows)
    notional = cfg.initial_mid * max(cfg.max_inventory, 1)
    returns = path["pnl"] / notional
    metrics = compute_risk_metrics(returns, periods_per_year=252 * 390)
    metrics.update(
        {
            "ending_equity": float(path["equity"].iloc[-1]),
            "avg_abs_inventory": float(path["inventory"].abs().mean()),
            "max_abs_inventory": float(path["inventory"].abs().max()),
            "fill_count": float(path["bid_fill"].sum() + path["ask_fill"].sum()),
        }
    )
    return SimulationResult(path=path, metrics=metrics, config=cfg)


def profile_market_maker(config: MarketMakingConfig | None = None, *, repeats: int = 5) -> dict[str, float]:
    """Return lightweight profiling metrics for the simulator."""

    elapsed: list[float] = []
    rows = 0
    for i in range(repeats):
        cfg = config or MarketMakingConfig(seed=17 + i)
        start = perf_counter()
        result = run_market_making_simulation(cfg)
        elapsed.append(perf_counter() - start)
        rows += len(result.path)
    total = sum(elapsed)
    return {
        "runs": float(repeats),
        "rows": float(rows),
        "elapsed_seconds": float(total),
        "rows_per_second": float(rows / total) if total > 0 else 0.0,
    }

