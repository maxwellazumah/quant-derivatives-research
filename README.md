# Quant Derivatives Research

Professional Python research repo for three derivatives projects:

1. Options analytics pipeline.
2. Discrete-time market-making simulator.
3. Dealer-hedging pressure proxy research.

The code is intentionally research-honest. It uses deterministic synthetic fixtures and optional sanitized local snapshots, makes provenance explicit, and avoids fake performance claims. The repo is not a live trading system and does not include broker credentials, private keys, personal career documents, or raw proprietary dumps.

## Quickstart

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
python scripts/run_all.py
```

Open the notebooks after installing requirements:

```powershell
jupyter lab notebooks
```

## Architecture

```text
src/
  data/               Synthetic fixtures, snapshot loaders, schema checks.
  options_pipeline/   Pricing, Greeks, IV features, walk-forward validation.
  market_making/      Discrete-time quoting and inventory-risk simulator.
  hedging_pressure/   GEX/vanna/charm-style public-data pressure proxies.
notebooks/            Reproducible project demos that import package code.
tests/                Unit tests for data, pricing, validation, simulator, proxies.
reports/              Ten build-pass reviews and generated sample metrics.
```

## Project 1: Options Analytics Pipeline

The pipeline validates option-chain snapshots, computes Black-Scholes prices, inverts implied volatility, derives Greeks, builds smile/term/liquidity features, and validates simple signals with chronological walk-forward splits.

Core functions:

- `load_option_snapshot`
- `generate_synthetic_chain`
- `compute_iv_surface_features`
- `build_walk_forward_labels`
- `walk_forward_option_signal_validation`
- `compute_risk_metrics`

Research questions:

- Which IV features are robust enough to survive schema checks and walk-forward validation?
- Where do RV/IV, skew, term slope, and liquidity disagree?
- How sensitive are historical-looking signals to split selection and missing data?

## Project 2: Discrete-Time Market-Making Simulator

The simulator models a quote engine over discrete steps with stochastic fills, inventory skew, adverse-selection stress, fees, and PnL attribution. It is meant for policy comparison and risk education, not exchange connectivity.

Core functions:

- `MarketMakingConfig`
- `run_market_making_simulation`
- `profile_market_maker`

Research questions:

- How do inventory limits change drawdown and fill count?
- What quote skew reduces inventory without destroying spread capture?
- Which assumptions dominate simulated market-maker PnL?

## Project 3: Dealer-Hedging Pressure Proxy

The pressure model builds transparent GEX/vanna/charm-style features from option open interest, Greeks, strike distance, and pin-zone concentration. It explicitly labels these as public-data proxies, not private dealer-book estimates.

Core functions:

- `compute_dealer_pressure_proxies`
- `build_pressure_dashboard_frame`
- `walk_forward_pressure_validation`

Research questions:

- Where does open interest concentrate relative to spot?
- Which strikes create the largest proxy gamma pressure?
- Do pressure proxies have any walk-forward relationship with future returns?

## Data Policy

This public repo is safe-by-default:

- Deterministic synthetic fixtures are always available.
- Sanitized local snapshots may be used only if they pass schema and secrets checks.
- `data/raw/`, `.env`, tokens, keys, broker files, and generated caches are ignored.
- Metrics shown in notebooks are sample or synthetic-fixture outputs unless a user explicitly supplies external data.

## Validation

Run:

```powershell
python -m py_compile (Get-ChildItem -Recurse -Filter *.py | ForEach-Object FullName)
pytest -q
python scripts/run_all.py
```

Before publishing, run a secrets scan:

```powershell
rg -n --hidden -S "PRIVATE KEY|BEGIN .*KEY|api[_-]?key|secret|password|token|etrade|kalshi" .
```

Matches inside `.gitignore`, README warnings, or this command are expected; matches in committed data/code are not.

## Portfolio Project Metrics

Truthful bullets after validation:

- Built a typed Python derivatives research repo covering option-chain analytics, market-making simulation, and dealer-pressure proxy research.
- Implemented deterministic synthetic fixtures, schema validation, IV/Greek feature engineering, walk-forward tests, risk metrics, and profiling hooks.
- Added reproducible notebooks, unit tests, ten review reports, and publication hygiene designed for a public GitHub portfolio.

## Caveats

This repository is for research and portfolio demonstration. It does not provide investment advice, live market data, broker execution, private flow estimates, or guaranteed trading performance.


