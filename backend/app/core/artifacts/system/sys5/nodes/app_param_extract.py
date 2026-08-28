"""Hybrid node: valid App Parameter rows for this feature."""
from __future__ import annotations

from ._marker_extract import extract_valid_rows
from ..schema import AppParameter
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore


def build(store: InMemoryWorkbookStore, llm, tools: list):
    def node(state: PipelineState) -> PipelineState:
        feature_id = state["feature_id"]
        rows = extract_valid_rows(store, "app_param", feature_id, llm, tools)
        params = [
            AppParameter(
                parameter_id=row.get("Parameter ID"),
                parameter_name=row.get("Parameter Name"),
                parameter_description=row.get("Parameter Description"),
                parameter_type=row.get("Parameter Type"),
                unit=row.get("Unit"),
                valid_value=row.get("Parameter Valid Value"),
                default_value=row.get("Parameter default value"),
                min_value=row.get("Parameter min Value"),
                max_value=row.get("Parameter max Value"),
                resolution=row.get("Resolution"),
            )
            for row in rows
        ]
        return {**state, "app_param_valid": params}

    return node
