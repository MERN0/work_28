"""Agent node: select relevant compound commands and library functions per
requirement, via a Python-computed keyword-overlap shortlist + one single-shot
LLM selection call (plan Decision 3). Selections are hallucination-checked
before being kept.

The shortlist itself is still mechanical, unchanged from before - only *how*
the LLM sees it changed: Python now fetches each shortlisted candidate's full
detail (`store.get_compound_command(name)`) and embeds it directly in the
prompt, rather than exposing the search/detail calls as tools the LLM could
choose to invoke mid-conversation (see agents.py's module docstring for why).
"""
from __future__ import annotations

from pydantic import BaseModel

from .. import excel_io
from ..agents import call_llm
from ..logging_utils import get_logger, stage_timer
from ..prompts import get_prompt
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


class _Selection(BaseModel):
    name: str
    reason: str


class _CompoundLibrarySelection(BaseModel):
    compound_commands: list[_Selection]
    library_calls: list[_Selection]


def _format_compound_candidates(store: InMemoryWorkbookStore, shortlist: list[dict]) -> str:
    parts = []
    for entry in shortlist:
        cmd = store.get_compound_command(entry["name"])
        if cmd is None:
            continue
        steps = "; ".join(f"{s.keyword_line}" + (f" (expected={s.expected_value})" if s.expected_value else "") for s in cmd.steps)
        parts.append(f"- Compound {cmd.name} [{cmd.source_sheet}] steps: {steps or '(no steps)'}")
    return "\n".join(parts) or "(no candidates found)"


def _format_library_candidates(shortlist: list[dict]) -> str:
    parts = [f"- {entry['signature']} - {entry['description'] or ''}" for entry in shortlist]
    return "\n".join(parts) or "(no candidates found)"


def build(store: InMemoryWorkbookStore, llm, pipeline_config=None):
    compound_top_k = pipeline_config.compound_command_shortlist_size if pipeline_config else 30
    library_top_k = pipeline_config.library_shortlist_size if pipeline_config else 30

    def node(state: PipelineState) -> PipelineState:
        selections: dict[str, dict] = {}
        for req in state["requirements"]:
            with stage_timer(_logger, "compound_command_map", req=req.req_id):
                query = f"{req.description} {req.verification_criteria or ''}"
                compound_shortlist = store.search_compound_commands(query, top_k=compound_top_k)
                library_shortlist = store.search_library(query, top_k=library_top_k)

                prompt = get_prompt("compound_command_map")
                user_input = (
                    f"Feature: {state.get('feature_name', '')}\n"
                    f"Requirement {req.req_id}: {req.description}\n"
                    f"Verification Criteria: {req.verification_criteria}\n"
                    f"Variant: {req.variant}\n\n"
                    f"Candidate compound commands (keyword-shortlisted, full step detail below - select from "
                    f"this list only, do not invent a name that isn't here):\n"
                    f"{_format_compound_candidates(store, compound_shortlist)}\n\n"
                    f"Candidate library functions (keyword-shortlisted - select from this list only):\n"
                    f"{_format_library_candidates(library_shortlist)}"
                )
                result = call_llm(llm, prompt, user_input, _CompoundLibrarySelection, pipeline_config=pipeline_config)

                valid_compounds = [s.model_dump() for s in result.compound_commands if store.exists("compound_command", s.name)]
                valid_libs = [
                    s.model_dump() for s in result.library_calls if store.exists("library_call", excel_io.leading_identifier(s.name))
                ]
                selections[req.req_id] = {"compound_commands": valid_compounds, "library_calls": valid_libs}
                _logger.info(
                    "compound_command_map: req=%s -> %d compound command(s), %d library call(s) (of %d/%d proposed)",
                    req.req_id, len(valid_compounds), len(valid_libs), len(result.compound_commands), len(result.library_calls),
                )

        return {**state, "compound_selections": selections}

    return node
