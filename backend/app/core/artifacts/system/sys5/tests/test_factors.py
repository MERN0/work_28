from __future__ import annotations

import pytest

from ..factors import MissingFactorTableError, get_factor_table


def test_known_feature_returns_table():
    table = get_factor_table("002")
    assert table.feature_id == "002"
    assert any(f.name == "Direction Switch" for f in table.fixed_factors)


def test_feature_019_is_also_registered_for_slope_assist():
    # 019 is the real System-Requirements Index-sheet feature id for Slope
    # Assist (confirmed from the Master Input Output Signals sheet); 002 is
    # the test spec document's own numbering. Same factor content, both ids.
    table_019 = get_factor_table("019")
    table_002 = get_factor_table("002")
    assert table_019.feature_id == "019"
    assert [f.name for f in table_019.fixed_factors] == [f.name for f in table_002.fixed_factors]
    assert [f.values for f in table_019.fixed_factors] == [f.values for f in table_002.fixed_factors]
    assert [f.name for f in table_019.variable_factors] == [f.name for f in table_002.variable_factors]


def test_unknown_feature_fails_fast_instead_of_guessing():
    with pytest.raises(MissingFactorTableError):
        get_factor_table("999")
