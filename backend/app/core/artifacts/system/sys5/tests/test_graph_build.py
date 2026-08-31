"""Confirms both StateGraphs compile without a real LLM/proxy - catches
structural wiring bugs (bad node names in conditional-edge maps, missing
edges) independently of whether the LLM proxy is reachable. Both the combined
and separate validation-pass graph shapes are exercised (plan Decision on
pipeline_config.combine_validation_passes)."""
from __future__ import annotations

import pytest

from ..config import Settings
from ..graph import _build_inner_test_case_graph, _build_outer_graph
from ..pipeline_config import PipelineConfig
from ..workbook_store import InMemoryWorkbookStore


def _settings() -> Settings:
    return Settings(
        project_name="tmhc_demo", username="", version="V1.0", domain="automotive", artifact="SYS5",
        model="", input_folder_path="", output_folder_path="/tmp", output_dir="/tmp",
        uploaded_files=[], req_filename="reqs.xlsx", req_sheet_name="002",
    )


@pytest.mark.parametrize("combine_validation_passes", [True, False])
def test_inner_and_outer_graphs_compile(fixture_paths, feature_id, combine_validation_passes):
    pipeline_config = PipelineConfig(combine_validation_passes=combine_validation_passes)
    store = InMemoryWorkbookStore.load(fixture_paths, feature_id, pipeline_config)
    settings = _settings()
    llm = object()  # never invoked - build_* only wires nodes, doesn't call the LLM
    tools: list = []

    inner = _build_inner_test_case_graph(store, llm, tools, settings, pipeline_config)
    assert inner is not None

    outer = _build_outer_graph(store, llm, tools, settings, inner, pipeline_config)
    assert outer is not None
