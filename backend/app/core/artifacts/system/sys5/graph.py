"""Builds the LangGraph `StateGraph` this pipeline runs, and `run_pipeline()`,
the top-level function `sys5.generate()` calls.

Three stages, wired as a fixed linear sequence via `add_edge` - no branching:

    feature_index -> requirements_extract -> test_pattern_gen

Each stage is a plain function `PipelineState -> Partial[PipelineState]`
(https://docs.langchain.com/oss/python/langgraph/graph-api). `add_node(name,
fn)` registers one, `add_edge(a, b)` is an unconditional transition,
`set_entry_point(name)` marks the start, and `.compile()` turns the builder
into something `.invoke(initial_state)`-able
(https://reference.langchain.com/python/langgraph/graph/state/StateGraph).

No checkpointer is configured - `generate()` is a single synchronous call
with no pause/resume requirement, so there's nothing to checkpoint against.
"""
from __future__ import annotations

import time

from langgraph.graph import END, StateGraph

from .config import Settings
from .llm import get_llm
from .logging_utils import get_logger, stage_timer
from .nodes import feature_index, load_inputs, requirements_extract, test_pattern_gen
from .pipeline_config import PipelineConfig
from .state import PipelineState
from .workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


def _build_graph(store: InMemoryWorkbookStore, llm, pipeline_config: PipelineConfig):
    graph = StateGraph(PipelineState)
    graph.add_node("feature_index", feature_index.build(store))
    graph.add_node("requirements_extract", requirements_extract.build(store, pipeline_config))
    graph.add_node("test_pattern_gen", test_pattern_gen.build(store, llm, pipeline_config))

    graph.set_entry_point("feature_index")
    graph.add_edge("feature_index", "requirements_extract")
    graph.add_edge("requirements_extract", "test_pattern_gen")
    graph.add_edge("test_pattern_gen", END)
    return graph.compile()


def run_pipeline(settings: Settings, pipeline_config: PipelineConfig | None = None) -> PipelineState:
    pipeline_config = pipeline_config or PipelineConfig.load()
    started = time.monotonic()
    _logger.info("run_pipeline starting: feature=%s model=%s", settings.req_sheet_name, pipeline_config.llm_model)

    with stage_timer(_logger, "load_inputs"):
        store = load_inputs.load_inputs(settings, pipeline_config)
    llm = get_llm(pipeline_config, model=settings.model or None)

    graph = _build_graph(store, llm, pipeline_config)
    initial_state: PipelineState = {"feature_id": settings.req_sheet_name}
    with stage_timer(_logger, "graph"):
        final_state = graph.invoke(initial_state)

    _logger.info("run_pipeline finished in %.1fs total", time.monotonic() - started)
    return final_state
