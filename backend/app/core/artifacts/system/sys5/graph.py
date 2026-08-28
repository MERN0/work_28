"""Outer StateGraph (per-feature pipeline) and inner per-test-case subgraph
(the validation/correction loop, plan §E), plus run_pipeline() which wires
everything together for sys5.py's entry point.

No checkpointer is wired up (plan Fix 9): generate() is a single synchronous
call with no pause/resume requirement.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from .config import Settings
from .llm import get_llm
from .nodes import (
    app_param_extract,
    comm_matrix_extract,
    compound_command_map,
    correct,
    feature_index,
    finalize_pass,
    generate,
    hallucination_check,
    io_signal_extract,
    load_inputs,
    model_mapping_resolve,
    output_assemble,
    requirements_extract,
    test_case_loop,
    test_pattern_gen,
    validate,
)
from .schema import Requirement
from .state import PipelineState, TestCaseState
from .tools import build_tools
from .workbook_store import InMemoryWorkbookStore


def route_after_hallucination(state: TestCaseState) -> str:
    """Module-level (not a closure) so the routing logic itself is directly
    unit-testable without building a graph or an LLM - see tests/test_graph_routing.py."""
    if state.get("hallucination_ok", True):
        return "validate_pass1"
    if state.get("correction_attempted", False):
        return "finalize_pass"
    return "correct"


def route_after_pass2(state: TestCaseState) -> str:
    pass1 = state.get("pass1_result")
    pass2 = state.get("pass2_result")
    both_passed = (pass1 is None or pass1.passed) and (pass2 is None or pass2.passed)
    if both_passed or state.get("correction_attempted", False):
        return "finalize_pass"
    return "correct"


def _build_inner_test_case_graph(store: InMemoryWorkbookStore, llm, tools: list, settings: Settings):
    """One node per validation-loop stage; conditional edges implement the
    '2 validation passes + 1 correction attempt' rule from plan §E."""
    graph = StateGraph(TestCaseState)
    graph.add_node("generate", generate.build(llm, tools, settings))
    graph.add_node("hallucination_check", hallucination_check.build(store))
    graph.add_node("validate_pass1", validate.build_pass1(llm, tools, settings))
    graph.add_node("validate_pass2", validate.build_pass2(llm, tools, settings))
    graph.add_node("correct", correct.build(llm, tools, settings))
    graph.add_node("finalize_pass", finalize_pass.build())

    graph.set_entry_point("generate")
    graph.add_edge("generate", "hallucination_check")
    graph.add_conditional_edges(
        "hallucination_check",
        route_after_hallucination,
        {"validate_pass1": "validate_pass1", "correct": "correct", "finalize_pass": "finalize_pass"},
    )
    graph.add_edge("validate_pass1", "validate_pass2")
    graph.add_conditional_edges(
        "validate_pass2", route_after_pass2, {"finalize_pass": "finalize_pass", "correct": "correct"}
    )
    graph.add_edge("correct", "hallucination_check")
    graph.add_edge("finalize_pass", END)
    return graph.compile()


def _context_builder(state: PipelineState, req: Requirement) -> dict:
    selections = state.get("compound_selections", {}).get(req.req_id, {})
    return {
        "feature_name": state.get("feature_name", ""),
        "factor_signal_resolutions": state.get("factor_signal_resolutions", {}),
        "compound_commands": selections.get("compound_commands", []),
        "library_calls": selections.get("library_calls", []),
    }


def _build_outer_graph(store: InMemoryWorkbookStore, llm, tools: list, settings: Settings, test_case_graph):
    graph = StateGraph(PipelineState)
    graph.add_node("feature_index", feature_index.build(store))
    graph.add_node("requirements_extract", requirements_extract.build(store, llm, tools))
    graph.add_node("comm_matrix_extract", comm_matrix_extract.build(store, llm, tools))
    graph.add_node("app_param_extract", app_param_extract.build(store, llm, tools))
    graph.add_node("io_signal_extract", io_signal_extract.build(store, llm, tools))
    graph.add_node("test_pattern_gen", test_pattern_gen.build(store, llm, tools))
    graph.add_node("model_mapping_resolve", model_mapping_resolve.build(store, llm, tools))
    graph.add_node("compound_command_map", compound_command_map.build(store, llm, tools))
    graph.add_node("test_case_loop", test_case_loop.build(test_case_graph, _context_builder))
    graph.add_node("output_assemble", output_assemble.build(settings))

    graph.set_entry_point("feature_index")
    graph.add_edge("feature_index", "requirements_extract")
    graph.add_edge("requirements_extract", "comm_matrix_extract")
    graph.add_edge("comm_matrix_extract", "app_param_extract")
    graph.add_edge("app_param_extract", "io_signal_extract")
    graph.add_edge("io_signal_extract", "test_pattern_gen")
    graph.add_edge("test_pattern_gen", "model_mapping_resolve")
    graph.add_edge("model_mapping_resolve", "compound_command_map")
    graph.add_edge("compound_command_map", "test_case_loop")
    graph.add_edge("test_case_loop", "output_assemble")
    graph.add_edge("output_assemble", END)
    return graph.compile()


def run_pipeline(settings: Settings) -> PipelineState:
    store = load_inputs.load_inputs(settings)
    llm = get_llm(settings.model)
    tools = build_tools(store)

    inner_graph = _build_inner_test_case_graph(store, llm, tools, settings)
    outer_graph = _build_outer_graph(store, llm, tools, settings, inner_graph)

    initial_state: PipelineState = {"feature_id": settings.req_sheet_name}
    return outer_graph.invoke(initial_state)
