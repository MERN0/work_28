from __future__ import annotations

from ..factors import get_factor_table
from ..nodes.test_pattern_gen import _PatternPlan, _ScenarioPlan, _expand


def test_expand_combines_only_applicable_fixed_factors():
    table = get_factor_table("002")
    plan = _PatternPlan(
        scenarios=[
            _ScenarioPlan(
                scenario_id="enable-on-slope",
                variable_transitions={"Option Set": "Disabled -> Enabled", "Slope angle": "0 deg -> 3 deg"},
                applicable_fixed_factor_names=["Truck Size", "Power Control Mode", "Direction Switch", "Load Capacity"],
            )
        ]
    )
    rows = _expand(plan, table)
    # Truck Size(2) x Power Control Mode(3) x Direction Switch(2) x Load Capacity(2) = 24
    assert len(rows) == 24
    assert {r.test_case_no for r in rows} == set(range(1, 25))
    assert all(r.variable_transitions["Slope angle"] == "0 deg -> 3 deg" for r in rows)
    assert all("Discharge Capacity" not in r.fixed_values for r in rows)  # not marked applicable, so excluded


def test_expand_respects_excluded_values():
    table = get_factor_table("002")
    plan = _PatternPlan(
        scenarios=[
            _ScenarioPlan(
                scenario_id="fwd-only",
                variable_transitions={"Option Set": "Disabled -> Enabled"},
                applicable_fixed_factor_names=["Direction Switch"],
                excluded_fixed_factor_values={"Direction Switch": ["BWD"]},
            )
        ]
    )
    rows = _expand(plan, table)
    assert len(rows) == 1
    assert rows[0].fixed_values == {"Direction Switch": "FWD"}


def test_expand_concatenates_multiple_scenarios_with_running_counter():
    table = get_factor_table("002")
    plan = _PatternPlan(
        scenarios=[
            _ScenarioPlan(scenario_id="s1", variable_transitions={}, applicable_fixed_factor_names=["Direction Switch"]),
            _ScenarioPlan(scenario_id="s2", variable_transitions={}, applicable_fixed_factor_names=["Load Capacity"]),
        ]
    )
    rows = _expand(plan, table)
    assert len(rows) == 4  # 2 + 2
    assert [r.test_case_no for r in rows] == [1, 2, 3, 4]
    assert [r.scenario_id for r in rows] == ["s1", "s1", "s2", "s2"]
