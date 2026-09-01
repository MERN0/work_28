"""Regression tests for a real production bug: `TestStep.ref_kind` used to be
filled in by the LLM independently of `TestStep.keyword`, so a step's keyword
and ref_kind could disagree (e.g. keyword=Compound but ref_kind=signal) -
hallucination_check then checked a real name against the wrong candidate
pool and failed a name that actually existed. `keyword` alone determines
what a step references; nothing else needs to (or should) decide it. These
tests cover both the pure mapping (`schema.derive_ref_kind`) and that
`generate.py`/`correct.py` actually overwrite whatever ref_kind the LLM
produced rather than trusting it.
"""
from __future__ import annotations

from ..nodes import correct, generate
from ..pipeline_config import PipelineConfig
from ..schema import Requirement, TestCase, TestPatternRow, TestStep, derive_ref_kind


def test_derive_ref_kind_covers_every_keyword():
    assert derive_ref_kind("Test_start") == "none"
    assert derive_ref_kind("End_of_test") == "none"
    assert derive_ref_kind("Wait") == "none"
    assert derive_ref_kind("Set") == "signal"
    assert derive_ref_kind("Verify") == "signal"
    assert derive_ref_kind("Wait_Until") == "signal"
    assert derive_ref_kind("Read") == "signal"
    assert derive_ref_kind("ReadStore") == "signal"
    assert derive_ref_kind("FIU") == "signal"
    assert derive_ref_kind("Compound") == "compound_command"
    assert derive_ref_kind("Config_Tol") == "tolerance"
    assert derive_ref_kind("Lib") == "library_call"


def _requirement() -> Requirement:
    return Requirement(req_id="REQ-1", description="desc", category="Functional Requirement")


def _row() -> TestPatternRow:
    return TestPatternRow(test_case_no=1, scenario_id="s1", fixed_values={}, variable_transitions={})


def _mismatched_step() -> TestStep:
    # An LLM answer that gets the ref_kind wrong for its own keyword - the
    # exact shape of the real bug (Compound keyword, but ref_kind=signal).
    return TestStep(step_no=1, phase="ACTION", keyword="Compound", target_ref="Power_On_A1", ref_kind="signal", step_text="Compound Power_On_A1")


def test_generate_overwrites_llm_ref_kind_from_keyword(monkeypatch):
    class _Result:
        description = "desc"
        steps = [_mismatched_step()]

    monkeypatch.setattr(generate, "call_llm", lambda *a, **kw: _Result())

    node = generate.build(llm=None, settings=None, pipeline_config=PipelineConfig())
    state = {"requirement": _requirement(), "pattern_row": _row(), "context": {}}
    result = node(state)

    step = result["test_case"].steps[0]
    assert step.keyword == "Compound"
    assert step.ref_kind == "compound_command"  # not "signal", regardless of what the LLM said


def test_correct_overwrites_llm_ref_kind_from_keyword(monkeypatch):
    class _Result:
        description = "desc"
        steps = [_mismatched_step()]

    monkeypatch.setattr(correct, "call_llm", lambda *a, **kw: _Result())

    original = TestCase(
        test_case_id="TC-1", feature="F", requirement_ids=["REQ-1"], description="orig", steps=[],
    )
    node = correct.build(llm=None, settings=None, pipeline_config=PipelineConfig())
    state = {"requirement": _requirement(), "test_case": original, "context": {}, "issues": ["some issue"]}
    result = node(state)

    step = result["test_case"].steps[0]
    assert step.keyword == "Compound"
    assert step.ref_kind == "compound_command"
