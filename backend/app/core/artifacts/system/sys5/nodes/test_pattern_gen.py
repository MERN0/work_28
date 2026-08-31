"""Agent node: build each requirement's Test Pattern (plan Decision 7).

The LLM identifies the distinct testable scenarios in Verification Criteria
and which fixed factors/values apply to each; Python then does the actual
combinatorial expansion (mechanical, not a judgment call).
"""
from __future__ import annotations

import itertools

from pydantic import BaseModel, Field

from ..agents import call_llm
from ..factors import get_factor_table
from ..logging_utils import get_logger, stage_timer
from ..prompts import get_prompt
from ..schema import FactorTable, Requirement, TestPatternRow, format_heading_info
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


class _ScenarioPlan(BaseModel):
    scenario_id: str
    variable_transitions: dict[str, str]           # factor name -> "A -> B"
    applicable_fixed_factor_names: list[str]         # subset of the feature's fixed factor names
    excluded_fixed_factor_values: dict[str, list[str]] = Field(default_factory=dict)  # factor name -> values to exclude


class _PatternPlan(BaseModel):
    scenarios: list[_ScenarioPlan]


def _expand(plan: _PatternPlan, table: FactorTable) -> list[TestPatternRow]:
    rows: list[TestPatternRow] = []
    counter = 1
    fixed_by_name = {f.name: f for f in table.fixed_factors}
    for scenario in plan.scenarios:
        chosen = [fixed_by_name[name] for name in scenario.applicable_fixed_factor_names if name in fixed_by_name]
        value_lists = [
            [v for v in factor.values if v not in scenario.excluded_fixed_factor_values.get(factor.name, [])]
            for factor in chosen
        ]
        combos = list(itertools.product(*value_lists)) if value_lists else [()]
        for combo in combos:
            rows.append(
                TestPatternRow(
                    test_case_no=counter,
                    scenario_id=scenario.scenario_id,
                    fixed_values=dict(zip([f.name for f in chosen], combo)),
                    variable_transitions=dict(scenario.variable_transitions),
                )
            )
            counter += 1
    return rows


def build(store: InMemoryWorkbookStore, llm, pipeline_config=None):
    def node(state: PipelineState) -> PipelineState:
        table = get_factor_table(state["feature_id"])
        patterns: dict[str, list[TestPatternRow]] = {}

        fixed_desc = "\n".join(f"- {f.name}: {f.values}" for f in table.fixed_factors)
        variable_desc = "\n".join(f"- {f.name}: {f.values}" for f in table.variable_factors)
        heading_context = format_heading_info(state.get("heading_info", []))

        for req in state["requirements"]:
            with stage_timer(_logger, "test_pattern_gen", req=req.req_id):
                prompt = get_prompt("test_pattern_gen")
                user_input = (
                    f"Requirement {req.req_id}: {req.description}\n"
                    f"Verification Criteria: {req.verification_criteria}\n"
                    f"Variant: {req.variant}\n\n"
                    f"Feature's fixed factors (combine combinatorially):\n{fixed_desc}\n\n"
                    f"Feature's variable factors (the transitions actually under test):\n{variable_desc}"
                    + (f"\n\nBackground context from Heading/Information rows on the requirement "
                       f"sheet (not requirements themselves, but may clarify intent):\n{heading_context}"
                       if heading_context else "")
                )
                result = call_llm(llm, prompt, user_input, _PatternPlan, pipeline_config=pipeline_config)
                patterns[req.req_id] = _expand(result, table)
                _logger.info("test_pattern_gen: req=%s -> %d test-pattern row(s)", req.req_id, len(patterns[req.req_id]))

        return {**state, "test_patterns": patterns}

    return node
