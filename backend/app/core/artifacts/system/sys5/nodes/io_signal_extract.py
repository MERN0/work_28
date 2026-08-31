"""Hybrid node: valid Master Input Output Signal rows for this feature."""
from __future__ import annotations

from ._marker_extract import extract_valid_rows
from ..logging_utils import get_logger, stage_timer
from ..schema import IOSignal
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


def build(store: InMemoryWorkbookStore, llm, tools: list, pipeline_config=None):
    def node(state: PipelineState) -> PipelineState:
        feature_id = state["feature_id"]
        with stage_timer(_logger, "io_signal_extract", feature_id=feature_id):
            rows = extract_valid_rows(store, "io_signal", feature_id, llm, tools, pipeline_config)
            signals = [
                IOSignal(
                    signal_id=row.get("Signal ID"),
                    logical_signal_name=row.get("Logical Signal Name"),
                    signal_type=row.get("Signal Type"),
                    variants=row.get("Variants"),
                    ecu=row.get("ECU"),
                    input_output=row.get("Input/Output"),
                )
                for row in rows
            ]
        return {**state, "io_signal_valid": signals}

    return node
