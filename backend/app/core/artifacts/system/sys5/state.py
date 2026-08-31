"""LangGraph state schemas.

The InMemoryWorkbookStore (raw sheet grids, ~700 compound commands, etc.) is
deliberately NOT a state field - per plan Fix 9, it's injected into node
closures by the graph builder instead, so it never needs to flow through
(and never risks being serialized by) LangGraph state handling. No
checkpointer is wired up: generate() is a single synchronous call with no
pause/resume requirement, so state can stay a plain in-process object.
"""
from __future__ import annotations

from typing import Any, Optional, TypedDict

from .schema import (
    AppParameter,
    CommMatrixSignal,
    HeadingInfoRow,
    IOSignal,
    ProducedManifest,
    Requirement,
    TestCase,
    TestPatternRow,
    ValidationResult,
)


class PipelineState(TypedDict, total=False):
    feature_id: str
    feature_name: str
    function_group: str

    requirements: list[Requirement]
    heading_info: list[HeadingInfoRow]

    comm_matrix_valid: list[CommMatrixSignal]
    app_param_valid: list[AppParameter]
    io_signal_valid: list[IOSignal]

    test_patterns: dict[str, list[TestPatternRow]]           # req_id -> pattern rows
    factor_signal_resolutions: dict[str, dict[str, Any]]       # "FactorName::Value" -> {signal, model_input, model_output_to_ecu}
    compound_selections: dict[str, dict[str, list[dict]]]      # req_id -> {"compound_commands": [...], "library_calls": [...]}

    test_cases: list[TestCase]
    manifest: ProducedManifest


class TestCaseState(TypedDict, total=False):
    """Inner per-test-case subgraph state (see graph.py)."""
    requirement: Requirement
    pattern_row: TestPatternRow
    context: dict[str, Any]  # feature_name, factor_signal_resolutions, compound/library selections

    test_case: Optional[TestCase]
    issues: list[str]
    hallucination_ok: bool
    pass1_result: Optional[ValidationResult]
    pass2_result: Optional[ValidationResult]
    correction_attempted: bool
    final_test_case: Optional[TestCase]


def valid_signal_names(state: PipelineState) -> list[str]:
    """This feature's known-valid signal/command names, from the already
    -extracted comm-matrix/IO-signal rows - used to give `model_mapping_resolve`
    and `generate`'s single-shot LLM calls a real, bounded list of names to
    reference instead of a tool they'd have to call to find out (see
    agents.py's module docstring)."""
    names: list[str] = []
    for sig in state.get("comm_matrix_valid", []):
        names += [n for n in (sig.signal_name, sig.logical_signal_name, sig.command_name) if n]
    for sig in state.get("io_signal_valid", []):
        if sig.logical_signal_name:
            names.append(sig.logical_signal_name)
    return sorted(set(names))
