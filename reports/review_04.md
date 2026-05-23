# Review 04 - Surface Features

## Bugs Found

- Chain features are often hard to audit when moneyness, term, skew, and liquidity are computed in separate notebooks.

## Improvements Made

- Centralized IV surface feature engineering in package code.
- Added moneyness, log-moneyness, ATM IV, put-skew proxy, term-slope proxy, RV/IV-style spread, and liquidity score fields.

## Portfolio Metrics

- Created reusable option-surface features for systematic research and notebook-level inspection.


