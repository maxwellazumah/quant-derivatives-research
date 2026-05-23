"""Dealer hedging pressure proxies built from public option-chain fields.

These are proxy features, not claims about private dealer books.  The goal is to
create transparent, testable pressure measures from open interest, gamma, skew,
and spot/strike geometry.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from options_pipeline.features import compute_iv_surface_features
from options_pipeline.risk import compute_risk_metrics


def _safe_rank_corr(left: pd.Series, right: pd.Series) -> float:
    left_rank = left.rank()
    right_rank = right.rank()
    if left_rank.nunique() < 2 or right_rank.nunique() < 2:
        return 0.0
    corr = left_rank.corr(right_rank)
    return 0.0 if pd.isna(corr) else float(corr)


def compute_dealer_pressure_proxies(chain: pd.DataFrame, *, contract_multiplier: int = 100) -> pd.DataFrame:
    """Compute GEX, vanna, and charm-style pressure proxies by contract."""

    features = compute_iv_surface_features(chain)
    df = features.copy()
    option_sign = np.where(df["option_type"] == "C", 1.0, -1.0)
    df["dealer_gamma_exposure"] = option_sign * df["gamma"] * df["open_interest"] * contract_multiplier * (df["spot"] ** 2) * 0.01
    df["dealer_vanna_proxy"] = option_sign * df["vanna_proxy"] * df["open_interest"] * contract_multiplier
    df["dealer_charm_proxy"] = option_sign * df["charm_proxy"] * df["open_interest"] * contract_multiplier
    df["distance_to_spot_pct"] = df["strike"] / df["spot"] - 1.0
    df["pin_weight"] = np.exp(-abs(df["distance_to_spot_pct"]) * 40.0) * df["open_interest"]
    df["pressure_source"] = np.where(df["is_synthetic"], "synthetic_proxy", "public_or_local_proxy")
    return df[
        [
            "as_of",
            "symbol",
            "expiry",
            "option_type",
            "strike",
            "spot",
            "iv",
            "delta",
            "gamma",
            "open_interest",
            "volume",
            "dealer_gamma_exposure",
            "dealer_vanna_proxy",
            "dealer_charm_proxy",
            "pin_weight",
            "pressure_source",
        ]
    ].reset_index(drop=True)


def build_pressure_dashboard_frame(pressure: pd.DataFrame) -> pd.DataFrame:
    """Aggregate contract-level pressure into a strike/expiry dashboard table."""

    grouped = (
        pressure.groupby(["as_of", "symbol", "expiry", "strike"], as_index=False)
        .agg(
            spot=("spot", "mean"),
            net_gamma_exposure=("dealer_gamma_exposure", "sum"),
            net_vanna_proxy=("dealer_vanna_proxy", "sum"),
            net_charm_proxy=("dealer_charm_proxy", "sum"),
            total_open_interest=("open_interest", "sum"),
            total_volume=("volume", "sum"),
            pin_weight=("pin_weight", "sum"),
            pressure_source=("pressure_source", "first"),
        )
        .sort_values(["as_of", "expiry", "strike"])
    )
    scale = grouped["net_gamma_exposure"].abs().max()
    grouped["pressure_score"] = grouped["net_gamma_exposure"] / scale if scale and scale > 0 else 0.0
    grouped["pin_zone_score"] = grouped["pin_weight"] / grouped["pin_weight"].max() if grouped["pin_weight"].max() > 0 else 0.0
    return grouped.reset_index(drop=True)


def walk_forward_pressure_validation(
    pressure_dashboard: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    horizon: int = 5,
) -> pd.DataFrame:
    """Validate whether pressure proxies align with future underlying returns."""

    daily = (
        pressure_dashboard.groupby("as_of", as_index=False)
        .agg(
            pressure_signal=("pressure_score", "mean"),
            pin_concentration=("pin_zone_score", "max"),
        )
    )
    labels = labels.copy()
    labels["as_of"] = pd.to_datetime(labels["as_of"])
    daily["as_of"] = pd.to_datetime(daily["as_of"])
    merged = daily.merge(labels[["as_of", f"fwd_ret_{horizon}d"]], on="as_of", how="inner").dropna()
    if merged.empty:
        return pd.DataFrame(
            [
                {
                    "n_obs": 0.0,
                    "ic": 0.0,
                    "strategy_return": 0.0,
                    "sharpe": 0.0,
                    "max_drawdown": 0.0,
                    "validation_mode": "walk_forward_proxy",
                }
            ]
        )
    position = np.where(merged["pressure_signal"] >= merged["pressure_signal"].expanding().median().shift(1).fillna(0), 1.0, -1.0)
    strategy_ret = position * merged[f"fwd_ret_{horizon}d"]
    metrics = compute_risk_metrics(strategy_ret, periods_per_year=max(1, 252 // horizon))
    ic = _safe_rank_corr(merged["pressure_signal"], merged[f"fwd_ret_{horizon}d"])
    return pd.DataFrame(
        [
            {
                "n_obs": float(len(merged)),
                "ic": ic,
                "strategy_return": float((1.0 + strategy_ret).prod() - 1.0),
                "sharpe": metrics["sharpe"],
                "max_drawdown": metrics["max_drawdown"],
                "validation_mode": "walk_forward_proxy",
            }
        ]
    )
