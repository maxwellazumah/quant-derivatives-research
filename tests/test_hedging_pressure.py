import numpy as np
import pandas as pd

from data.synthetic import generate_synthetic_chain, generate_underlying_series
from hedging_pressure.proxies import build_pressure_dashboard_frame, compute_dealer_pressure_proxies, walk_forward_pressure_validation
from options_pipeline.features import build_walk_forward_labels


def test_pressure_proxies_and_dashboard_are_labeled():
    pressure = compute_dealer_pressure_proxies(generate_synthetic_chain())
    assert "dealer_gamma_exposure" in pressure.columns
    assert set(pressure["pressure_source"]) == {"synthetic_proxy"}
    dashboard = build_pressure_dashboard_frame(pressure)
    assert np.isfinite(dashboard["pressure_score"]).all()
    assert dashboard["pin_zone_score"].between(0, 1).all()


def test_pressure_walk_forward_validation_returns_metrics():
    underlying = generate_underlying_series(periods=120)
    labels = build_walk_forward_labels(underlying)
    chains = []
    for idx, row in enumerate(underlying.iloc[::10].itertuples(index=False)):
        chains.append(generate_synthetic_chain(as_of=row.date, spot=float(row.close), seed=80 + idx))
    pressure = compute_dealer_pressure_proxies(pd.concat(chains, ignore_index=True))
    dashboard = build_pressure_dashboard_frame(pressure)
    validation = walk_forward_pressure_validation(dashboard, labels)
    assert validation["validation_mode"].iloc[0] == "walk_forward_proxy"
    assert np.isfinite(validation["ic"].iloc[0])

