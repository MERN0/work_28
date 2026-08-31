"""Regression test for a real hallucination-rate bug: comm_matrix_extract.py's
CommMatrixSignal.command_name is only populated when a signal's Command List
fuzzy match scores >= command_match_threshold (deterministic fast-path,
unaffected by this fix and still exists for other callers) - but generate.py
used to only ever see THAT gated value, so any signal whose true match
scored just under the cutoff never had its real command name shown to the
LLM at all, and the LLM guessed a plausible-looking-but-fake CAN_* name
instead (which then always failed the hallucination guardrail). graph.py's
_build_signal_reference recomputes top_k candidates fresh, unconditionally,
so the LLM always sees the real candidates and makes the judgment call
itself - exactly what these tests check.
"""
from __future__ import annotations

from ..graph import _build_signal_reference
from ..schema import CommMatrixSignal, IOSignal


class _FakeStore:
    """Returns a fixed scored-candidate list regardless of the lookup key -
    enough to prove _build_signal_reference surfaces candidates even for a
    signal whose CommMatrixSignal.command_name is None (below threshold)."""

    def __init__(self, candidates: list[dict]):
        self._candidates = candidates

    def lookup_command_name(self, signal_name, top_k=None):
        return self._candidates[: top_k or len(self._candidates)]


def test_signal_reference_shows_candidates_even_when_command_name_is_none():
    # command_name=None mirrors a real signal whose best match scored just
    # under command_match_threshold during comm_matrix_extract - the exact
    # case that used to leave the LLM with zero information.
    state = {
        "comm_matrix_valid": [
            CommMatrixSignal(
                signal_id="1", logical_signal_name="PwrCtrlMode", signal_name="Main_TxS_0x2020_0x01",
                command_name=None,
            )
        ],
        "io_signal_valid": [],
    }
    store = _FakeStore([{"command_name": "CAN_HIL_PwrCtrlMode", "signal_name": "Main_TxS_0x2020_0x01", "score": 79.0}])

    lines = _build_signal_reference(store, state)

    assert len(lines) == 1
    assert "PwrCtrlMode" in lines[0]
    assert "CAN_HIL_PwrCtrlMode" in lines[0]  # the real candidate is now visible despite scoring below threshold
    assert "match 79" in lines[0]


def test_signal_reference_reports_no_match_honestly():
    state = {"comm_matrix_valid": [CommMatrixSignal(logical_signal_name="Foo", signal_name="Bar")], "io_signal_valid": []}
    store = _FakeStore([])

    lines = _build_signal_reference(store, state)

    assert "no Command List match found" in lines[0]


def test_signal_reference_includes_io_signals_as_model_input():
    state = {"comm_matrix_valid": [], "io_signal_valid": [IOSignal(logical_signal_name="MDL_SEN_Slope_Angle")]}
    store = _FakeStore([])

    lines = _build_signal_reference(store, state)

    assert len(lines) == 1
    assert "MDL_SEN_Slope_Angle" in lines[0]
    assert "Model Input signal" in lines[0]
