"""Unit tests for the inner subgraph's conditional-edge routing logic (plan
§E), tested as pure functions - no LLM or graph execution required. The real
LLM proxy is unreachable from this sandbox, so full agent execution is
exercised only in the deployed environment (see plan's Verification plan)."""
from __future__ import annotations

from ..graph import route_after_hallucination, route_after_pass2
from ..schema import ValidationResult


def _result(passed: bool) -> ValidationResult:
    return ValidationResult(rubric="test", passed=passed)


def test_hallucination_fail_first_attempt_goes_to_correct():
    state = {"hallucination_ok": False, "correction_attempted": False}
    assert route_after_hallucination(state) == "correct"


def test_hallucination_fail_after_correction_goes_to_finalize():
    state = {"hallucination_ok": False, "correction_attempted": True}
    assert route_after_hallucination(state) == "finalize_pass"


def test_hallucination_ok_goes_to_validate_pass1():
    state = {"hallucination_ok": True, "correction_attempted": False}
    assert route_after_hallucination(state) == "validate_pass1"


def test_both_passes_pass_goes_to_finalize():
    state = {"pass1_result": _result(True), "pass2_result": _result(True), "correction_attempted": False}
    assert route_after_pass2(state) == "finalize_pass"


def test_one_pass_fails_first_attempt_goes_to_correct():
    state = {"pass1_result": _result(False), "pass2_result": _result(True), "correction_attempted": False}
    assert route_after_pass2(state) == "correct"

    state2 = {"pass1_result": _result(True), "pass2_result": _result(False), "correction_attempted": False}
    assert route_after_pass2(state2) == "correct"


def test_one_pass_fails_after_correction_goes_to_finalize_flagged():
    state = {"pass1_result": _result(False), "pass2_result": _result(True), "correction_attempted": True}
    assert route_after_pass2(state) == "finalize_pass"


def test_missing_results_treated_as_passed():
    # a stage that never ran (e.g. skipped) must not block finalization
    assert route_after_pass2({"correction_attempted": False}) == "finalize_pass"
