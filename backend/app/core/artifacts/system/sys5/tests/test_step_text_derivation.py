"""Regression tests for a real output-quality bug: with no explicit rule,
the LLM wrote TestStep.step_text as a verbose sentence duplicating what
parameter_settings/expected_value/remarks already carry (e.g. "Set
CAN_HIL_PwrCtrlMode to P (model_input = 1)" instead of the bare "Set
CAN_HIL_PwrCtrlMode", "Wait for controller to process Power-Control-Mode"
instead of the bare "Wait"). schema.derive_step_text is the deterministic
fix (same principle as derive_ref_kind): keyword + target_ref fully
determine step_text for every keyword except Lib (whose step_text carries
real call arguments not present in target_ref), so generate.py/correct.py
discard the LLM's own step_text for every other keyword."""
from __future__ import annotations

from ..nodes import correct, generate
from ..pipeline_config import PipelineConfig
from ..schema import Requirement, TestCase, TestPatternRow, TestStep, derive_step_text


def test_derive_step_text_covers_every_non_lib_keyword():
    assert derive_step_text("Test_start", None, "fallback") == "Test_start"
    assert derive_step_text("End_of_test", None, "fallback") == "End_of_test"
    assert derive_step_text("Wait", None, "fallback") == "Wait"
    assert derive_step_text("Set", "CAN_HIL_PwrCtrlMode", "fallback") == "Set CAN_HIL_PwrCtrlMode"
    assert derive_step_text("Verify", "MDL_SWH_DIR_STATE", "fallback") == "Verify MDL_SWH_DIR_STATE"
    assert derive_step_text("Wait_Until", "MDL_SEN_Slope_Angle", "fallback") == "Wait_Until MDL_SEN_Slope_Angle"
    assert derive_step_text("Read", "MDL_SEN_Load", "fallback") == "Read MDL_SEN_Load"
    assert derive_step_text("ReadStore", "MDL_SEN_Load", "fallback") == "Read MDL_SEN_Load(StoreVariable)"
    assert derive_step_text("FIU", "MDL_SWH_DIR_STATE", "fallback") == "FIU MDL_SWH_DIR_STATE"
    assert derive_step_text("Compound", "Power_On_A1", "fallback") == "Compound Power_On_A1"
    # Config_Tol's target_ref is already the fully-qualified name from the
    # source data - no keyword prefix, unlike every other keyword above.
    assert derive_step_text("Config_Tol", "Config_Tol_rpm", "fallback") == "Config_Tol_rpm"


def test_derive_step_text_never_bakes_a_value_or_explanation_into_the_bare_form():
    # The exact real-bug shape: a verbose LLM answer must be discarded, not
    # merged with or appended to the deterministic bare form.
    verbose = "Set CAN_HIL_PwrCtrlMode to P (model_input = 1)"
    assert derive_step_text("Set", "CAN_HIL_PwrCtrlMode", verbose) == "Set CAN_HIL_PwrCtrlMode"
    assert "to P" not in derive_step_text("Set", "CAN_HIL_PwrCtrlMode", verbose)
    assert derive_step_text("Wait", None, "Wait for controller to process Power-Control-Mode") == "Wait"


def test_lib_keyword_keeps_the_llms_own_step_text():
    # Lib_ call arguments are genuinely LLM-authored content (real values,
    # not derivable from target_ref alone) - the one keyword left untouched.
    llm_text = "Lib_Ramp Signal_Name(Start=0,Stop=100,Step=10,Time=500)"
    assert derive_step_text("Lib", "Lib_Ramp", llm_text) == llm_text


def _requirement() -> Requirement:
    return Requirement(req_id="REQ-1", description="desc", category="Functional Requirement")


def _row() -> TestPatternRow:
    return TestPatternRow(test_case_no=1, scenario_id="s1", fixed_values={}, variable_transitions={})


def _verbose_set_step() -> TestStep:
    return TestStep(
        step_no=2, phase="PRECONDITION", keyword="Set", target_ref="CAN_HIL_PwrCtrlMode", ref_kind="signal",
        step_text="Set CAN_HIL_PwrCtrlMode to P (model_input = 1)", parameter_settings="P",
    )


def _lib_step() -> TestStep:
    return TestStep(
        step_no=3, phase="ACTION", keyword="Lib", target_ref="Lib_Ramp", ref_kind="library_call",
        step_text="Lib_Ramp Signal_Name(Start=0,Stop=100,Step=10,Time=500)",
    )


def test_generate_overwrites_verbose_llm_step_text(monkeypatch):
    class _Result:
        description = "desc"
        steps = [_verbose_set_step(), _lib_step()]

    monkeypatch.setattr(generate, "call_llm", lambda *a, **kw: _Result())

    node = generate.build(llm=None, settings=None, pipeline_config=PipelineConfig())
    state = {"requirement": _requirement(), "pattern_row": _row(), "context": {}}
    result = node(state)

    steps = result["test_case"].steps
    assert steps[0].step_text == "Set CAN_HIL_PwrCtrlMode"  # bare - no "to P (model_input = 1)"
    assert steps[1].step_text == "Lib_Ramp Signal_Name(Start=0,Stop=100,Step=10,Time=500)"  # Lib untouched


def test_correct_overwrites_verbose_llm_step_text(monkeypatch):
    class _Result:
        description = "desc"
        steps = [_verbose_set_step(), _lib_step()]

    monkeypatch.setattr(correct, "call_llm", lambda *a, **kw: _Result())

    original = TestCase(test_case_id="TC-1", feature="F", requirement_ids=["REQ-1"], description="orig", steps=[])
    node = correct.build(llm=None, settings=None, pipeline_config=PipelineConfig())
    state = {"requirement": _requirement(), "test_case": original, "context": {}, "issues": ["some issue"]}
    result = node(state)

    steps = result["test_case"].steps
    assert steps[0].step_text == "Set CAN_HIL_PwrCtrlMode"
    assert steps[1].step_text == "Lib_Ramp Signal_Name(Start=0,Stop=100,Step=10,Time=500)"
