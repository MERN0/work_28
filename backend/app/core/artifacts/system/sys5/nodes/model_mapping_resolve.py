"""Deterministic node: resolve every factor value in this feature's factor
table to its actual Model_Input_Mapping signal/value, once per feature
(shared across every requirement's test patterns, rather than re-resolved
per test case).

Exact/fuzzy lookup only (a factor's known `signal_ref`, plus a fuzzy match
of the factor value against that signal's Test Case Input text). A factor
value that doesn't cross `model_input_match_threshold` against anything in
the Model_Input_Mapping sheet is left unresolved and logged - not guessed -
same principle as requirements_extract's category classification.
"""
from __future__ import annotations

from .. import excel_io
from ..factors import get_factor_table
from ..logging_utils import get_logger, stage_timer
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


def build(store: InMemoryWorkbookStore, pipeline_config=None):
    input_threshold = pipeline_config.model_input_match_threshold if pipeline_config else 70

    def node(state: PipelineState) -> PipelineState:
        with stage_timer(_logger, "model_mapping_resolve", feature_id=state["feature_id"]):
            table = get_factor_table(state["feature_id"])
            resolved: dict[str, dict] = {}
            unresolved: list[tuple[str, str]] = []

            for factor in [*table.fixed_factors, *table.variable_factors]:
                for value in factor.values:
                    key = f"{factor.name}::{value}"
                    if factor.signal_ref:
                        rows = store.get_model_input_mapping(factor.signal_ref)
                        match = excel_io.fuzzy_find(value, [r.test_case_input or "" for r in rows], threshold=input_threshold)
                        row = next((r for r in rows if r.test_case_input == match), None) if match else None
                        if row:
                            resolved[key] = {
                                "signal": factor.signal_ref,
                                "model_input": row.model_input,
                                "model_output_to_ecu": row.model_output_to_ecu,
                            }
                            continue
                    unresolved.append((factor.name, value))

            if unresolved:
                _logger.warning(
                    "model_mapping_resolve: %d factor value(s) could not be resolved deterministically "
                    "(no Model_Input_Mapping row >= threshold %d) and are left unresolved: %s",
                    len(unresolved), input_threshold, unresolved,
                )
            _logger.info("model_mapping_resolve: %d resolved, %d unresolved", len(resolved), len(unresolved))

        return {**state, "factor_signal_resolutions": resolved}

    return node
