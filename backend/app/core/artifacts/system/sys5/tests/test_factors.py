from __future__ import annotations

import pytest

from ..factors import MissingFactorTableError, get_factor_table


def test_known_feature_returns_table():
    table = get_factor_table("002")
    assert table.feature_id == "002"
    assert any(f.name == "Direction Switch" for f in table.fixed_factors)


def test_unknown_feature_fails_fast_instead_of_guessing():
    with pytest.raises(MissingFactorTableError):
        get_factor_table("999")
