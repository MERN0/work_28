"""Agent node: build each requirement's Test Pattern (plan Decision 7).

The LLM identifies the distinct testable scenarios in Verification Criteria
and which fixed factors/values apply to each; Python then does the actual
combinatorial expansion (mechanical, not a judgment call).
"""
from __future__ import annotations

import itertools

from pydantic import BaseModel, Field

from ..agents import run_agent_with_structured_output
from ..factors import get_factor_table
from ..prompts import get_prompt
from ..schema import FactorTable, Requirement, TestPatternRow
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore


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


def build(store: InMemoryWorkbookStore, llm, tools: list):
    def node(state: PipelineState) -> PipelineState:
        table = get_factor_table(state["feature_id"])
        patterns: dict[str, list[TestPatternRow]] = {}

        fixed_desc = "\n".join(f"- {f.name}: {f.values}" for f in table.fixed_factors)
        variable_desc = "\n".join(f"- {f.name}: {f.values}" for f in table.variable_factors)

        for req in state["requirements"]:
            prompt = get_prompt("test_pattern_gen")
            user_input = (
                f"Requirement {req.req_id}: {req.description}\n"
                f"Verification Criteria: {req.verification_criteria}\n"
                f"Variant: {req.variant}\n\n"
                f"Feature's fixed factors (combine combinatorially):\n{fixed_desc}\n\n"
                f"Feature's variable factors (the transitions actually under test):\n{variable_desc}"
            )
            result, _ = run_agent_with_structured_output(llm, tools, prompt, user_input, _PatternPlan)
            patterns[req.req_id] = _expand(result, table)

        return {**state, "test_patterns": patterns}

    return node
