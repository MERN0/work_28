"""Confirms the StateGraph compiles without a real LLM/proxy - catches
structural wiring bugs (bad node names, missing edges) independently of
whether the LLM proxy is reachable."""
from __future__ import annotations

from ..graph import _build_graph
from ..pipeline_config import PipelineConfig
from ..workbook_store import InMemoryWorkbookStore


def test_graph_compiles(fixture_paths, feature_id):
    pipeline_config = PipelineConfig()
    store = InMemoryWorkbookStore.load(fixture_paths["requirements"], feature_id, pipeline_config)
    llm = object()  # never invoked - _build_graph only wires nodes, doesn't call the LLM

    graph = _build_graph(store, llm, pipeline_config)
    assert graph is not None
