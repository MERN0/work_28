"""Deterministic node: select relevant compound commands and library
functions per requirement via keyword-overlap search
(`InMemoryWorkbookStore.search_compound_commands`/`search_library`,
`rapidfuzz.fuzz.token_set_ratio` of the requirement text against each
candidate's name/steps or signature/description).

The top-scoring candidates are kept outright (already sorted best-first by
the store's search), capped at `compound_command_max_selected`/
`library_max_selected` and filtered to `compound_command_select_threshold`/
`library_select_threshold` - no LLM call, no invented name possible, since
every selection comes directly from the store's own candidate pool.
"""
from __future__ import annotations

from ..logging_utils import get_logger, stage_timer
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


def build(store: InMemoryWorkbookStore, pipeline_config=None):
    compound_max = pipeline_config.compound_command_max_selected if pipeline_config else 5
    library_max = pipeline_config.library_max_selected if pipeline_config else 5
    compound_threshold = pipeline_config.compound_command_select_threshold if pipeline_config else 45
    library_threshold = pipeline_config.library_select_threshold if pipeline_config else 45

    def node(state: PipelineState) -> PipelineState:
        selections: dict[str, dict] = {}
        for req in state["requirements"]:
            with stage_timer(_logger, "compound_command_map", req=req.req_id):
                query = f"{req.description} {req.verification_criteria or ''}"

                compound_matches = [
                    c for c in store.search_compound_commands(query, top_k=compound_max) if c["score"] >= compound_threshold
                ]
                library_matches = [
                    l for l in store.search_library(query, top_k=library_max) if l["score"] >= library_threshold
                ]

                selections[req.req_id] = {
                    "compound_commands": [{"name": c["name"]} for c in compound_matches],
                    "library_calls": [{"name": l["signature"]} for l in library_matches],
                }
                _logger.info(
                    "compound_command_map: req=%s -> %d compound command(s), %d library call(s)",
                    req.req_id, len(compound_matches), len(library_matches),
                )

        return {**state, "compound_selections": selections}

    return node
