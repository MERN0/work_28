"""Hybrid node: resolve every factor value in this feature's factor table to
its actual Model_Input_Mapping signal/value, once per feature (shared across
every requirement's test patterns, rather than re-resolved per test case).

Deterministic exact/fuzzy lookup first (when a factor has a known
`signal_ref`, or the Test Case Input text fuzzy-matches the factor value
cleanly); LLM escalation only for factor values that don't resolve cleanly.
"""
from __future__ import annotations

from pydantic import BaseModel

from .. import excel_io
from ..agents import run_agent_with_structured_output
from ..factors import get_factor_table
from ..logging_utils import get_logger, stage_timer
from ..prompts import get_prompt
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


class _ResolvedValue(BaseModel):
    factor_name: str
    value: str
    signal: str
    model_input: str
    model_output_to_ecu: str | None = None


class _ResolutionBatch(BaseModel):
    resolutions: list[_ResolvedValue]


def build(store: InMemoryWorkbookStore, llm, tools: list, pipeline_config=None):
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

            _logger.info("model_mapping_resolve: %d resolved via fast-path, %d need LLM escalation", len(resolved), len(unresolved))

            if unresolved:
                listing = "\n".join(f"- Factor {name!r}, value {value!r}" for name, value in unresolved)
                prompt = get_prompt("model_mapping_resolve")
                user_input = (
                    f"Feature: {state.get('feature_name', state['feature_id'])!r}\n"
                    f"Resolve the Model_Input_Mapping signal/value for each factor value below - use "
                    f"get_model_input_mapping to find the right Signal and matching Test Case Input row.\n\n{listing}"
                )
                result, _ = run_agent_with_structured_output(
                    llm, tools, prompt, user_input, _ResolutionBatch, pipeline_config=pipeline_config
                )
                for r in result.resolutions:
                    resolved[f"{r.factor_name}::{r.value}"] = {
                        "signal": r.signal,
                        "model_input": r.model_input,
                        "model_output_to_ecu": r.model_output_to_ecu,
                    }

        return {**state, "factor_signal_resolutions": resolved}

    return node
