"""Deterministic node: valid Comm Matrix (CAN) signal rows for this feature,
with each signal's Command name resolved via the Command List sheet."""
from __future__ import annotations

from .. import excel_io
from ._marker_extract import extract_valid_rows
from ..logging_utils import get_logger, stage_timer
from ..schema import CommMatrixSignal
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


def _s(row: dict, key: str) -> str | None:
    """Normalize a raw cell value to str|None before it reaches a pydantic
    model - see app_param_extract.py's `_s` for why this is needed (a
    numeric-looking cell, e.g. numeric Message IDs, reads as int/float and
    CommMatrixSignal's fields are plain `str`, which pydantic v2 won't
    coerce)."""
    return excel_io._norm(row.get(key)) or None


def build(store: InMemoryWorkbookStore, pipeline_config=None):
    command_match_threshold = pipeline_config.command_match_threshold if pipeline_config else 80

    def node(state: PipelineState) -> PipelineState:
        feature_id = state["feature_id"]
        with stage_timer(_logger, "comm_matrix_extract", feature_id=feature_id):
            rows = extract_valid_rows(store, "comm_matrix", feature_id)

            signals: list[CommMatrixSignal] = []
            for row in rows:
                signal_name = _s(row, "Signal name")
                command_name = None
                if signal_name:
                    candidates = store.lookup_command_name(signal_name, top_k=1)
                    if candidates and candidates[0]["score"] >= command_match_threshold:
                        command_name = candidates[0]["command_name"]
                signals.append(
                    CommMatrixSignal(
                        signal_id=_s(row, "Signal ID"),
                        message_name=_s(row, "Message Name"),
                        message_ids=_s(row, "Message IDs"),
                        logical_signal_name=_s(row, "Logical Signal Name"),
                        signal_name=signal_name,
                        signal_description=_s(row, "Signal Description"),
                        command_name=command_name,
                    )
                )
        return {**state, "comm_matrix_valid": signals}

    return node
