"""Plain-Python node: exact Index-sheet lookup for the feature id."""
from __future__ import annotations

from ..logging_utils import get_logger
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


def build(store: InMemoryWorkbookStore):
    def node(state: PipelineState) -> PipelineState:
        feature_id = state["feature_id"]
        info = store.get_feature_info(feature_id)
        if info is None:
            raise ValueError(f"Feature id {feature_id!r} was not found in the Index sheet")
        _logger.info("feature_index: feature=%s name=%r function_group=%r", feature_id, info["name"], info["function_group"])
        return {**state, "feature_name": info["name"], "function_group": info["function_group"]}

    return node
