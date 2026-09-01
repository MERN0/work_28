"""End-to-end test of sys5.generate(): feature_index -> requirements_extract
-> test_pattern_gen -> JSON file, with no real LLM/network call (call_llm is
stubbed at its call site in nodes/test_pattern_gen.py)."""
from __future__ import annotations

import json

from .. import sys5
from ..nodes import test_pattern_gen as test_pattern_gen_module
from ..nodes.test_pattern_gen import _FactorTransition, _PatternPlan, _ScenarioPlan


def _fake_call_llm(llm, system_prompt, user_input, output_schema, pipeline_config=None):
    return _PatternPlan(
        scenarios=[
            _ScenarioPlan(
                scenario_id="enable-on-slope",
                variable_transitions=[_FactorTransition(factor_name="Option Set", transition="Disabled -> Enabled")],
                applicable_fixed_factor_names=["Direction Switch"],
            )
        ]
    )


def test_generate_writes_json_with_test_patterns_for_every_requirement(fixture_paths, feature_id, tmp_path, monkeypatch):
    monkeypatch.setattr(test_pattern_gen_module, "call_llm", _fake_call_llm)

    output_dir = tmp_path / "out"
    config = {
        "project_name": "UnitTest",
        "input_folder_path": "",
        "output_dir": str(output_dir),
        "uploaded_files": [fixture_paths["requirements"]],
        "req_filename": "System Requirements.xlsx",
        "req_sheet_name": feature_id,
    }

    result_path = sys5.generate(config)

    assert result_path.endswith(".json")
    with open(result_path) as fh:
        payload = json.load(fh)

    assert payload["feature_id"] == feature_id
    assert payload["feature_name"] == "Slope Assist"
    # Both requirement rows classify as "Functional Requirement" (the second
    # row's typo'd category still fuzzy-matches at the configured threshold -
    # see test_requirements_extract.py for the exact threshold behavior); the
    # "Heading" row is dropped, never turned into a requirement.
    assert len(payload["requirements"]) == 2
    assert {r["req_id"] for r in payload["requirements"]} == {"TMHC_SYSRS_FR002001", "TMHC_SYSRS_FR002002"}

    req = next(r for r in payload["requirements"] if r["req_id"] == "TMHC_SYSRS_FR002001")
    assert req["category"] == "Functional Requirement"
    # Direction Switch has 2 values (FWD, BWD) -> 2 combinatorial rows.
    assert len(req["test_patterns"]) == 2
    assert {p["fixed_values"]["Direction Switch"] for p in req["test_patterns"]} == {"FWD", "BWD"}
