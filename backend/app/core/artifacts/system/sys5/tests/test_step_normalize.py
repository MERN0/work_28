"""Unit tests for nodes/_step_normalize.py's normalize_steps() - the shared
post-processing generate.py/correct.py both apply to every LLM-produced
TestStep. Uses a fake store (only resolve_ref matters here) rather than the
full fixture-backed InMemoryWorkbookStore - see test_workbook_store.py's
test_resolve_ref_returns_the_canonical_spelling_not_just_a_yes_no for the
same fix against real fixture data."""
from __future__ import annotations

from ..nodes._step_normalize import normalize_steps
from ..schema import TestStep


class _FakeStore:
    """Canonicalizes a name by dropping spaces/underscores and matching
    case-insensitively against a fixed table - enough to exercise
    normalize_steps() without needing a real workbook."""

    def __init__(self, canonical: dict[str, str]):
        self._canonical = canonical

    def resolve_ref(self, ref_kind, target_ref):
        key = target_ref.replace(" ", "").replace("_", "").lower()
        return self._canonical.get(key)


def _step(keyword, target_ref, step_text, ref_kind="signal") -> TestStep:
    return TestStep(step_no=1, phase="ACTION", keyword=keyword, target_ref=target_ref, ref_kind=ref_kind, step_text=step_text)


def test_canonicalizes_a_malformed_but_fuzzy_matching_target_ref():
    store = _FakeStore({"canhilhmode": "CAN_HIL_HMode"})
    steps = [_step("Set", "CAN HIL HMode", "Set CAN HIL HMode to Inactive (model_input = 0)")]

    result = normalize_steps(steps, store)

    assert result[0].target_ref == "CAN_HIL_HMode"  # canonical spelling, not the LLM's malformed one
    assert result[0].step_text == "Set CAN_HIL_HMode"  # derived from the corrected target_ref


def test_unresolvable_target_ref_is_left_unchanged_so_hallucination_check_still_flags_it():
    store = _FakeStore({})  # nothing resolves
    steps = [_step("Set", "Totally_Invented_Signal", "Set Totally_Invented_Signal")]

    result = normalize_steps(steps, store)

    assert result[0].target_ref == "Totally_Invented_Signal"


def test_none_store_skips_canonicalization_but_still_derives_ref_kind_and_step_text():
    steps = [
        TestStep(
            step_no=1, phase="ACTION", keyword="Compound", target_ref="Power_On_A1", ref_kind="signal",  # wrong on purpose
            step_text="some verbose LLM text",
        )
    ]

    result = normalize_steps(steps, store=None)

    assert result[0].target_ref == "Power_On_A1"  # unchanged - no store to resolve against
    assert result[0].ref_kind == "compound_command"  # still derived from keyword alone
    assert result[0].step_text == "Compound Power_On_A1"  # still derived from keyword+target_ref


def test_bare_wait_step_needs_no_store_lookup():
    store = _FakeStore({})
    steps = [_step("Wait", None, "Wait for controller to settle", ref_kind="none")]

    result = normalize_steps(steps, store)

    assert result[0].step_text == "Wait"
    assert result[0].target_ref is None
