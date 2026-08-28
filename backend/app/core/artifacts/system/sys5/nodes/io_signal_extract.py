"""Hybrid node: valid Master Input Output Signal rows for this feature."""
from __future__ import annotations

from ._marker_extract import extract_valid_rows
from ..schema import IOSignal
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore


def build(store: InMemoryWorkbookStore, llm, tools: list):
    def node(state: PipelineState) -> PipelineState:
        feature_id = state["feature_id"]
        rows = extract_valid_rows(store, "io_signal", feature_id, llm, tools)
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
