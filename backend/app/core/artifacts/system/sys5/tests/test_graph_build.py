"""Confirms both StateGraphs compile without a real LLM/proxy - catches
structural wiring bugs (bad node names in conditional-edge maps, missing
edges) independently of whether the LLM proxy is reachable."""
from __future__ import annotations

from ..config import Settings
from ..graph import _build_inner_test_case_graph, _build_outer_graph
from ..workbook_store import InMemoryWorkbookStore


def _settings() -> Settings:
    return Settings(
        project_name="tmhc_demo", username="", version="V1.0", domain="automotive", artifact="SYS5",
        model="", input_folder_path="", output_folder_path="/tmp", output_dir="/tmp",
        uploaded_files=[], req_filename="reqs.xlsx", req_sheet_name="002",
    )


def test_inner_and_outer_graphs_compile(fixture_paths, feature_id):
    store = InMemoryWorkbookStore.load(fixture_paths, feature_id)
    settings = _settings()
    llm = object()  # never invoked - build_* only wires nodes, doesn't call the LLM
    tools: list = []

    inner = _build_inner_test_case_graph(store, llm, tools, settings)
    assert inner is not None

    outer = _build_outer_graph(store, llm, tools, settings, inner)
    assert outer is not None
