# Review 03 - Pricing And Greeks

## Bugs Found

- IV inversion can silently produce unusable values when prices are at intrinsic value.
- Research examples need dependency-light pricing so the repo remains easy to run.

## Improvements Made

- Added Black-Scholes pricing, bisection implied-vol inversion, and Greeks without requiring SciPy.
- Added intrinsic-value handling and bounded IV search.

## Portfolio Metrics

- Built dependency-light derivatives pricing primitives with unit-testable IV round trips.


