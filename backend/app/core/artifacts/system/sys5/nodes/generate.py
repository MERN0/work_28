"""Inner subgraph node: write one test case for one test-pattern row."""
from __future__ import annotations

from pydantic import BaseModel

from ..agents import run_agent_with_structured_output
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
        f"Selected compound commands for this requirement: {context.get('compound_commands', [])}\n"
        f"Selected library calls for this requirement: {context.get('library_calls', [])}\n"
    )


def build(llm, tools: list, settings, pipeline_config=None):
    def node(state: TestCaseState) -> TestCaseState:
        req = state["requirement"]
        row = state["pattern_row"]
        context = state.get("context", {})
        prompt = get_prompt("generate", settings)
        _logger.info("generating test case: req=%s scenario=%s", req.req_id, row.scenario_id)
        result, _ = run_agent_with_structured_output(
            llm, tools, prompt, _build_user_input(state), _GeneratedTestCase, pipeline_config=pipeline_config
        )

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
