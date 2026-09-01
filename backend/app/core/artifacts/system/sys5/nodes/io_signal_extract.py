"""Deterministic node: valid Master Input Output Signal rows for this feature."""
from __future__ import annotations

from .. import excel_io
from ._marker_extract import extract_valid_rows
from ..logging_utils import get_logger, stage_timer
from ..schema import IOSignal
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


def _s(row: dict, key: str) -> str | None:
    """Normalize a raw cell value to str|None before it reaches a pydantic
    model - see app_param_extract.py's `_s` for why this is needed (a
    numeric-looking cell, e.g. a numeric Signal ID, reads as int/float and
    IOSignal's fields are plain `str`, which pydantic v2 won't coerce)."""
    return excel_io._norm(row.get(key)) or None


def build(store: InMemoryWorkbookStore, pipeline_config=None):
    def node(state: PipelineState) -> PipelineState:
        feature_id = state["feature_id"]
        with stage_timer(_logger, "io_signal_extract", feature_id=feature_id):
            rows = extract_valid_rows(store, "io_signal", feature_id)
            signals = [
                IOSignal(
                    signal_id=_s(row, "Signal ID"),
                    logical_signal_name=_s(row, "Logical Signal Name"),
                    signal_type=_s(row, "Signal Type"),
                    variants=_s(row, "Variants"),
                    ecu=_s(row, "ECU"),
                    input_output=_s(row, "Input/Output"),
                )
                for row in rows
            ]
        return {**state, "io_signal_valid": signals}

    return node
