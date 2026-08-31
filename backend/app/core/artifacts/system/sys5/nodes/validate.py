"""Inner subgraph nodes: the semantic validation pass(es) - requirement-
fidelity and engineering-plausibility, two distinct rubrics (plan §E).

Two modes, chosen by `pipeline_config.combine_validation_passes`:
- separate (build_pass1 + build_pass2): the original two-LLM-call design.
- combined (build_combined, default): both rubrics answered in ONE LLM call,
  roughly halving this stage's LLM round trips with no loss of rubric
  coverage - see prompts.py's "validate_combined".
"""
from __future__ import annotations

from ..agents import call_llm
from ..logging_utils import get_logger
from ..prompts import get_prompt
from ..schema import CombinedValidationResult, ValidationResult
from ..state import TestCaseState

_logger = get_logger(__name__)


def _user_input(state: TestCaseState) -> str:
    req = state["requirement"]
    test_case = state["test_case"]
    return (
        f"Requirement {req.req_id}: {req.description}\n"
        f"Verification Criteria: {req.verification_criteria}\n\n"
        f"Test case under review:\n{test_case.model_dump_json(indent=2)}"
    )


def _build(rubric_stage: str, result_key: str, llm, settings, pipeline_config):
    def node(state: TestCaseState) -> TestCaseState:
        prompt = get_prompt(rubric_stage, settings)
        result = call_llm(llm, prompt, _user_input(state), ValidationResult, pipeline_config=pipeline_config)
        _logger.info("validation[%s] req=%s passed=%s issues=%d", rubric_stage, state["requirement"].req_id, result.passed, len(result.issues))
        return {**state, result_key: result}

    return node


def build_pass1(llm, settings, pipeline_config=None):
    return _build("validate_pass1", "pass1_result", llm, settings, pipeline_config)


def build_pass2(llm, settings, pipeline_config=None):
    return _build("validate_pass2", "pass2_result", llm, settings, pipeline_config)


def build_combined(llm, settings, pipeline_config=None):
    def node(state: TestCaseState) -> TestCaseState:
        prompt = get_prompt("validate_combined")
        result = call_llm(llm, prompt, _user_input(state), CombinedValidationResult, pipeline_config=pipeline_config)
        pass1 = result.fidelity.model_copy(update={"rubric": "validate_pass1"})
        pass2 = result.plausibility.model_copy(update={"rubric": "validate_pass2"})
        _logger.info(
            "validation[combined] req=%s fidelity_passed=%s plausibility_passed=%s issues=%d",
            state["requirement"].req_id, pass1.passed, pass2.passed, len(pass1.issues) + len(pass2.issues),
        )
        return {**state, "pass1_result": pass1, "pass2_result": pass2}

    return node
