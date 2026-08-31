"""Inner subgraph node: write one test case for one test-pattern row.

All context this stage's LLM call needs (valid signals, tolerances, the
already-selected compound commands' full step detail, the already-selected
library entries' full signatures) is assembled in Python by
`graph.py`'s context builder and embedded directly in the prompt - see
agents.py's module docstring for why this stage makes one single-shot call
rather than giving the LLM tools to look these up mid-conversation. By the
time this stage runs, everything it could need is already small and
feature-scoped (earlier stages already narrowed it down), so there's nothing
this prompt is missing that a tool call would have found instead.
`hallucination_check` still validates every reference the LLM actually used
afterward, unchanged.
"""
from __future__ import annotations

from pydantic import BaseModel

from ..agents import call_llm
from ..logging_utils import get_logger
from ..prompts import get_prompt
from ..schema import TestCase, TestStep
from ..state import TestCaseState

_logger = get_logger(__name__)


class _GeneratedTestCase(BaseModel):
    description: str
    steps: list[TestStep]


def _build_user_input(state: TestCaseState) -> str:
    req = state["requirement"]
    row = state["pattern_row"]
    context = state.get("context", {})
    return (
        f"Requirement {req.req_id}: {req.description}\n"
        f"Verification Criteria: {req.verification_criteria}\n"
        f"Variant: {req.variant}\nPriority: {req.priority}\n\n"
        f"Test pattern row (scenario {row.scenario_id}):\n"
        f"Fixed factor values: {row.fixed_values}\n"
        f"Variable factor transitions: {row.variable_transitions}\n\n"
        f"Resolved factor signal mappings (factor::value -> signal/model_input/model_output_to_ecu):\n"
        f"{context.get('factor_signal_resolutions', {})}\n\n"
        f"This feature's valid signals: {', '.join(context.get('valid_signals', [])) or '(none)'}\n\n"
        f"Available tolerances (Config_Tol_*):\n" + "\n".join(context.get("tolerances", [])) + "\n\n"
        f"Selected compound commands for this requirement (full step detail - use these exact names):\n"
        + "\n".join(context.get("compound_command_details", [])) + "\n\n"
        f"Selected library calls for this requirement (use these exact bare names):\n"
        + "\n".join(context.get("library_details", []))
        + (
            f"\n\nBackground context from Heading/Information rows on the requirement sheet "
            f"(not requirements themselves, but may clarify intent):\n{context['heading_info']}\n"
            if context.get("heading_info")
            else ""
        )
    )


def build(llm, settings, pipeline_config=None):
    def node(state: TestCaseState) -> TestCaseState:
        req = state["requirement"]
        row = state["pattern_row"]
        context = state.get("context", {})
        prompt = get_prompt("generate", settings)
        _logger.info("generating test case: req=%s scenario=%s", req.req_id, row.scenario_id)
        result = call_llm(llm, prompt, _build_user_input(state), _GeneratedTestCase, pipeline_config=pipeline_config)

        test_case = TestCase(
            test_case_id="PENDING",
            feature=context.get("feature_name", ""),
            variant=req.variant,
            requirement_ids=[req.req_id],
            priority=req.priority,
            description=result.description,
            steps=result.steps,
        )
        return {
            **state,
            "test_case": test_case,
            "issues": [],
            "correction_attempted": state.get("correction_attempted", False),
        }

    return node
