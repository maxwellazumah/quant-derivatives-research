"""Run all three research examples and write a compact metrics artifact."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from data.synthetic import generate_synthetic_chain, generate_underlying_series
from hedging_pressure.proxies import build_pressure_dashboard_frame, compute_dealer_pressure_proxies, walk_forward_pressure_validation
from market_making.simulator import MarketMakingConfig, profile_market_maker, run_market_making_simulation
from options_pipeline.features import build_walk_forward_labels, compute_iv_surface_features, walk_forward_option_signal_validation


def main() -> None:
    reports_dir = ROOT / "reports" / "generated"
    reports_dir.mkdir(parents=True, exist_ok=True)
    underlying = generate_underlying_series(periods=220)
    labels = build_walk_forward_labels(underlying)
    chains = []
    for idx, row in enumerate(underlying.iloc[::10].itertuples(index=False)):
        chains.append(generate_synthetic_chain(as_of=row.date, spot=float(row.close), seed=11 + idx))
    chain = __import__("pandas").concat(chains, ignore_index=True)
    features = compute_iv_surface_features(chain)
    option_validation = walk_forward_option_signal_validation(features, labels)
    mm = run_market_making_simulation(MarketMakingConfig(steps=750))
    pressure = compute_dealer_pressure_proxies(chain)
    pressure_dashboard = build_pressure_dashboard_frame(pressure)
    pressure_validation = walk_forward_pressure_validation(pressure_dashboard, labels)
    metrics = {
        "options_pipeline": {
            "rows": int(len(features)),
            "walk_forward_splits": int(len(option_validation)),
            "mean_ic": float(option_validation["ic"].mean()) if len(option_validation) else 0.0,
        },
        "market_making": {
            "ending_equity": mm.metrics["ending_equity"],
            "max_abs_inventory": mm.metrics["max_abs_inventory"],
            "fills": mm.metrics["fill_count"],
            "profile": profile_market_maker(MarketMakingConfig(steps=250), repeats=3),
        },
        "hedging_pressure": {
            "rows": int(len(pressure_dashboard)),
            "validation": pressure_validation.iloc[0].to_dict(),
        },
        "research_caveat": "All metrics are deterministic sample or synthetic-fixture results, not live trading claims.",
    }
    out = reports_dir / "sample_metrics.json"
    out.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    print(json.dumps(metrics, indent=2, default=str))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
