"""Agent node: select relevant compound commands and library functions per
requirement, via keyword-overlap shortlist tools + LLM selection (plan
Decision 3). Selections are hallucination-checked before being kept.
"""
from __future__ import annotations

from pydantic import BaseModel

from ..agents import run_agent_with_structured_output
from ..prompts import get_prompt
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore


class _Selection(BaseModel):
    name: str
    reason: str


class _CompoundLibrarySelection(BaseModel):
    compound_commands: list[_Selection]
    library_calls: list[_Selection]


def build(store: InMemoryWorkbookStore, llm, tools: list):
    def node(state: PipelineState) -> PipelineState:
        selections: dict[str, dict] = {}
        for req in state["requirements"]:
            prompt = get_prompt("compound_command_map")
            user_input = (
                f"Feature: {state.get('feature_name', '')}\n"
                f"Requirement {req.req_id}: {req.description}\n"
                f"Verification Criteria: {req.verification_criteria}\n"
                f"Variant: {req.variant}"
            )
            result, _ = run_agent_with_structured_output(llm, tools, prompt, user_input, _CompoundLibrarySelection)

            valid_compounds = [s.model_dump() for s in result.compound_commands if store.exists("compound_command", s.name)]
            valid_libs = [
                s.model_dump() for s in result.library_calls if store.exists("library_call", s.name.split("(")[0].strip())
            ]
            selections[req.req_id] = {"compound_commands": valid_compounds, "library_calls": valid_libs}

        return {**state, "compound_selections": selections}

    return node
