import pandas as pd
import pytest

from data.schema import validate_option_schema
from data.synthetic import generate_synthetic_chain, generate_underlying_series


def test_synthetic_chain_valid_schema_and_provenance():
    chain = generate_synthetic_chain(seed=123)
    report = validate_option_schema(chain, raise_on_error=False)
    assert report.valid
    assert len(chain) > 20
    assert chain["is_synthetic"].all()
    assert set(chain["source"]) == {"deterministic_synthetic"}


def test_schema_flags_bad_quotes():
    chain = generate_synthetic_chain()
    chain.loc[0, "ask"] = chain.loc[0, "bid"] - 0.01
    with pytest.raises(ValueError, match="ask"):
        validate_option_schema(chain)


def test_underlying_series_is_reproducible():
    a = generate_underlying_series(seed=5)
    b = generate_underlying_series(seed=5)
    pd.testing.assert_frame_equal(a, b)
    assert a["realized_vol_21d"].gt(0).all()

