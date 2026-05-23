import numpy as np

from market_making.simulator import MarketMakingConfig, profile_market_maker, run_market_making_simulation


def test_market_making_simulation_is_deterministic():
    cfg = MarketMakingConfig(steps=200, seed=99)
    a = run_market_making_simulation(cfg)
    b = run_market_making_simulation(cfg)
    assert a.path["equity"].iloc[-1] == b.path["equity"].iloc[-1]
    assert a.path["inventory"].abs().max() <= cfg.max_inventory
    assert np.isfinite(a.metrics["ending_equity"])


def test_profile_hook_returns_throughput():
    profile = profile_market_maker(MarketMakingConfig(steps=50), repeats=2)
    assert profile["runs"] == 2
    assert profile["rows_per_second"] > 0

