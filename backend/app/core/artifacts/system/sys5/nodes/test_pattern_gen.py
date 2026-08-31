"""Agent node: build each requirement's Test Pattern (plan Decision 7).

The LLM identifies the distinct testable scenarios in Verification Criteria
and which fixed factors/values apply to each; Python then does the actual
combinatorial expansion (mechanical, not a judgment call). One LLM call per
requirement - the model only emits a small plan object, never the expanded
rows themselves.

## Why the plan schema uses lists of pairs, not dicts

`ChatOpenAI.with_structured_output` defaults to `method="json_schema"`, which
sends the schema as a strict `response_format` - and a self-hosted backend
(this deployment's vLLM behind litellm) compiles that schema into a grammar
for guided decoding. A pydantic `dict[str, str]` field becomes
`{"type": "object", "additionalProperties": {...}}` with no fixed
`properties`: an object with *arbitrary* keys, i.e. an effectively unbounded
grammar. That is pathological for constrained decoding - it made this stage
take minutes-to-never against the real endpoint while every other stage
(whose schemas are all fully closed) completed normally.

So every field here stays closed: a list of objects with fixed keys instead
of a map with free-form keys. `_expand` converts them back into the dicts
`TestPatternRow` actually stores, which costs nothing and keeps the wire
schema bounded.
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


class _FactorTransition(BaseModel):
    factor_name: str = Field(description="Exact name of one of the feature's variable factors.")
    transition: str = Field(description="The transition under test for that factor, e.g. '0 deg -> 3 deg'.")


class _ExcludedValues(BaseModel):
    factor_name: str = Field(description="Exact name of one of the feature's fixed factors.")
    excluded_values: list[str] = Field(description="Values of that factor to leave OUT of the combinatorial sweep.")


class _ScenarioPlan(BaseModel):
    scenario_id: str = Field(description="Short identifier for this scenario, e.g. 'slope_0_to_3_enabled'.")
    variable_transitions: list[_FactorTransition] = Field(
        description="One entry per variable factor this scenario exercises."
    )
    applicable_fixed_factor_names: list[str] = Field(
        description="Exact names of the fixed factors that apply to this scenario (these get swept combinatorially)."
    )
    excluded_fixed_factor_values: list[_ExcludedValues] = Field(
        default_factory=list,
        description="Optional. Only for fixed-factor values this requirement explicitly rules out.",
    )


class _PatternPlan(BaseModel):
    scenarios: list[_ScenarioPlan]


def _expand(plan: _PatternPlan, table: FactorTable) -> list[TestPatternRow]:
    rows: list[TestPatternRow] = []
    counter = 1
    fixed_by_name = {f.name: f for f in table.fixed_factors}
    for scenario in plan.scenarios:
        excluded = {e.factor_name: e.excluded_values for e in scenario.excluded_fixed_factor_values}
        transitions = {t.factor_name: t.transition for t in scenario.variable_transitions}
        chosen = [fixed_by_name[name] for name in scenario.applicable_fixed_factor_names if name in fixed_by_name]
        value_lists = [
            [v for v in factor.values if v not in excluded.get(factor.name, [])]
            for factor in chosen
        ]
        combos = list(itertools.product(*value_lists)) if value_lists else [()]
        for combo in combos:
            rows.append(
                TestPatternRow(
                    test_case_no=counter,
                    scenario_id=scenario.scenario_id,
                    fixed_values=dict(zip([f.name for f in chosen], combo)),
                    variable_transitions=dict(transitions),
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
