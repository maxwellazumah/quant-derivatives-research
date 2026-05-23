"""Feature engineering and walk-forward validation for option-chain research."""

from __future__ import annotations

import numpy as np
import pandas as pd

from data.schema import validate_option_schema
from .pricing import greeks, implied_volatility
from .risk import compute_risk_metrics


def _safe_rank_corr(left: pd.Series, right: pd.Series) -> float:
    """Spearman-style rank correlation that returns zero for constant inputs."""

    left_rank = left.rank()
    right_rank = right.rank()
    if left_rank.nunique() < 2 or right_rank.nunique() < 2:
        return 0.0
    corr = left_rank.corr(right_rank)
    return 0.0 if pd.isna(corr) else float(corr)


def compute_iv_surface_features(chain: pd.DataFrame, *, rate: float = 0.04) -> pd.DataFrame:
    """Add IV, Greeks, moneyness, skew, term, and liquidity features."""

    validate_option_schema(chain)
    df = chain.copy()
    df["as_of"] = pd.to_datetime(df["as_of"])
    df["expiry"] = pd.to_datetime(df["expiry"])
    df["option_type"] = df["option_type"].astype(str).str.upper()
    df["dte"] = (df["expiry"] - df["as_of"]).dt.days.clip(lower=1)
    df["tau"] = df["dte"] / 252.0
    df["moneyness"] = df["strike"] / df["spot"]
    df["log_moneyness"] = np.log(df["moneyness"])
    df["mid"] = ((df["bid"] + df["ask"]) / 2.0).where(df["mid"].isna() if "mid" in df else False, df["mid"])
    if "iv" not in df.columns or df["iv"].isna().any():
        df["iv"] = [
            implied_volatility(row.mid, row.spot, row.strike, rate, row.tau, row.option_type)
            for row in df.itertuples(index=False)
        ]
    greek_rows = [
        greeks(row.spot, row.strike, rate, row.iv, row.tau, row.option_type)
        for row in df.itertuples(index=False)
    ]
    greek_df = pd.DataFrame(greek_rows, index=df.index)
    df = pd.concat([df, greek_df], axis=1)
    df["quoted_spread_pct"] = (df["ask"] - df["bid"]) / df["mid"].clip(lower=0.01)
    df["liquidity_score"] = np.log1p(df["volume"]) + np.log1p(df["open_interest"]) - 5.0 * df["quoted_spread_pct"]
    atm = df.loc[df["moneyness"].sub(1.0).abs().groupby([df["as_of"], df["expiry"]]).idxmin(), ["as_of", "expiry", "iv"]]
    atm = atm.rename(columns={"iv": "atm_iv"})
    df = df.merge(atm, on=["as_of", "expiry"], how="left")
    skew = (
        df.assign(put_otm=np.where((df["option_type"] == "P") & (df["moneyness"] < 1), df["iv"], np.nan))
        .groupby(["as_of", "expiry"])["put_otm"]
        .mean()
        .rename("put_skew_iv")
        .reset_index()
    )
    df = df.merge(skew, on=["as_of", "expiry"], how="left")
    term = df.groupby(["as_of", "expiry"])["atm_iv"].mean().reset_index()
    term["term_rank"] = term.groupby("as_of")["expiry"].rank(method="dense")
    term_slope = term.groupby("as_of").apply(
        lambda x: float(x.sort_values("expiry")["atm_iv"].iloc[-1] - x.sort_values("expiry")["atm_iv"].iloc[0]),
        include_groups=False,
    )
    df = df.merge(term_slope.rename("atm_term_slope").reset_index(), on="as_of", how="left")
    if "realized_vol_21d" in df.columns:
        df["rv_iv_spread"] = df["realized_vol_21d"] - df["iv"]
    else:
        df["rv_iv_spread"] = df["atm_iv"] - df["iv"]
    return df.sort_values(["as_of", "expiry", "strike", "option_type"]).reset_index(drop=True)


def build_walk_forward_labels(underlying: pd.DataFrame, *, horizons: tuple[int, ...] = (1, 5, 21)) -> pd.DataFrame:
    """Create forward-return labels from an EOD underlying series."""

    df = underlying.copy()
    date_col = "date" if "date" in df.columns else "as_of"
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)
    out = pd.DataFrame({"as_of": df[date_col], "close": df["close"]})
    for horizon in horizons:
        out[f"fwd_ret_{horizon}d"] = df["close"].shift(-horizon) / df["close"] - 1.0
        out[f"fwd_sign_{horizon}d"] = np.sign(out[f"fwd_ret_{horizon}d"]).fillna(0.0)
    return out.dropna().reset_index(drop=True)


def walk_forward_option_signal_validation(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    signal_col: str = "rv_iv_spread",
    horizon: int = 5,
    n_splits: int = 4,
) -> pd.DataFrame:
    """Evaluate a simple option feature with chronological walk-forward splits."""

    if signal_col not in features.columns:
        raise KeyError(signal_col)
    daily_signal = features.groupby("as_of")[signal_col].mean().rename("signal").reset_index()
    labels = labels.copy()
    labels["as_of"] = pd.to_datetime(labels["as_of"])
    merged = daily_signal.merge(labels[["as_of", f"fwd_ret_{horizon}d"]], on="as_of", how="inner").dropna()
    if len(merged) < n_splits + 2:
        return pd.DataFrame(columns=["split", "train_start", "test_start", "test_end", "ic", "strategy_return", "sharpe", "max_drawdown"])
    splits = np.array_split(merged.index.to_numpy(), n_splits)
    rows: list[dict[str, object]] = []
    for i in range(1, len(splits)):
        train_idx = np.concatenate(splits[:i])
        test_idx = splits[i]
        train = merged.loc[train_idx]
        test = merged.loc[test_idx].copy()
        threshold = float(train["signal"].median())
        test["position"] = np.where(test["signal"] >= threshold, 1.0, -1.0)
        test["strategy_ret"] = test["position"] * test[f"fwd_ret_{horizon}d"]
        ic = _safe_rank_corr(test["signal"], test[f"fwd_ret_{horizon}d"]) if len(test) > 2 else 0.0
        metrics = compute_risk_metrics(test["strategy_ret"], periods_per_year=max(1, 252 // horizon))
        rows.append(
            {
                "split": i,
                "train_start": train["as_of"].min(),
                "test_start": test["as_of"].min(),
                "test_end": test["as_of"].max(),
                "ic": ic,
                "strategy_return": float((1.0 + test["strategy_ret"]).prod() - 1.0),
                "sharpe": metrics["sharpe"],
                "max_drawdown": metrics["max_drawdown"],
            }
        )
    return pd.DataFrame(rows)
