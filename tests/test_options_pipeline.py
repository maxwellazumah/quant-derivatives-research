import numpy as np

from data.synthetic import generate_synthetic_chain, generate_underlying_series
from options_pipeline.features import build_walk_forward_labels, compute_iv_surface_features, walk_forward_option_signal_validation
from options_pipeline.pricing import black_scholes_price, implied_volatility
from options_pipeline.risk import compute_risk_metrics


def test_pricing_and_iv_roundtrip():
    price = black_scholes_price(100, 100, 0.03, 0.2, 30 / 252, "C")
    iv = implied_volatility(price, 100, 100, 0.03, 30 / 252, "C")
    assert abs(iv - 0.2) < 1e-3


def test_surface_features_are_finite():
    chain = generate_synthetic_chain()
    features = compute_iv_surface_features(chain)
    for col in ["iv", "delta", "gamma", "vega", "liquidity_score", "atm_term_slope"]:
        assert np.isfinite(features[col]).all()
    assert {"C", "P"} == set(features["option_type"])


def test_walk_forward_validation_uses_chronological_splits():
    underlying = generate_underlying_series(periods=160)
    labels = build_walk_forward_labels(underlying)
    chains = []
    for idx, row in enumerate(underlying.iloc[::8].itertuples(index=False)):
        chains.append(generate_synthetic_chain(as_of=row.date, spot=float(row.close), seed=40 + idx))
    import pandas as pd

    features = compute_iv_surface_features(pd.concat(chains, ignore_index=True))
    wf = walk_forward_option_signal_validation(features, labels, n_splits=4)
    assert len(wf) >= 1
    assert np.isfinite(wf["ic"]).all()
    assert (wf["test_start"] <= wf["test_end"]).all()


def test_risk_metrics_handle_empty_and_nonempty():
    assert compute_risk_metrics([])["n_obs"] == 0
    metrics = compute_risk_metrics([0.01, -0.005, 0.003])
    assert metrics["n_obs"] == 3
    assert np.isfinite(metrics["sharpe"])

