"""Risk and validation metrics used across the three projects."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_risk_metrics(returns: pd.Series | np.ndarray, *, periods_per_year: int = 252) -> dict[str, float]:
    """Compute standard research metrics from a return series."""

    series = pd.Series(returns, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    if series.empty:
        return {
            "n_obs": 0.0,
            "total_return": 0.0,
            "annualized_return": 0.0,
            "annualized_vol": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown": 0.0,
            "hit_rate": 0.0,
        }
    equity = (1.0 + series).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    ann_return = float(equity.iloc[-1] ** (periods_per_year / max(len(series), 1)) - 1.0)
    ann_vol = float(series.std(ddof=0) * np.sqrt(periods_per_year))
    sharpe = float((series.mean() / series.std(ddof=0)) * np.sqrt(periods_per_year)) if series.std(ddof=0) > 0 else 0.0
    downside = series[series < 0]
    sortino = float((series.mean() / downside.std(ddof=0)) * np.sqrt(periods_per_year)) if len(downside) > 1 and downside.std(ddof=0) > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    return {
        "n_obs": float(len(series)),
        "total_return": total_return,
        "annualized_return": ann_return,
        "annualized_vol": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": float(drawdown.min()),
        "hit_rate": float((series > 0).mean()),
    }

