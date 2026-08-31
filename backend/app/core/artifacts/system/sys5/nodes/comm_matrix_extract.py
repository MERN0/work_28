"""Hybrid node: valid Comm Matrix (CAN) signal rows for this feature, with
each signal's Command name resolved via the Command List sheet."""
from __future__ import annotations

from ._marker_extract import extract_valid_rows
from ..logging_utils import get_logger, stage_timer
from ..schema import CommMatrixSignal
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


def build(store: InMemoryWorkbookStore, llm, tools: list, pipeline_config=None):
    command_match_threshold = pipeline_config.command_match_threshold if pipeline_config else 80

    def node(state: PipelineState) -> PipelineState:
        feature_id = state["feature_id"]
        with stage_timer(_logger, "comm_matrix_extract", feature_id=feature_id):
            rows = extract_valid_rows(store, "comm_matrix", feature_id, llm, tools, pipeline_config)

            signals: list[CommMatrixSignal] = []
            for row in rows:
                signal_name = row.get("Signal name") or None
                command_name = None
                if signal_name:
                    candidates = store.lookup_command_name(signal_name, top_k=1)
                    if candidates and candidates[0]["score"] >= command_match_threshold:
                        command_name = candidates[0]["command_name"]
                signals.append(
                    CommMatrixSignal(
                        signal_id=row.get("Signal ID"),
                        message_name=row.get("Message Name"),
                        message_ids=row.get("Message IDs"),
                        logical_signal_name=row.get("Logical Signal Name"),
                        signal_name=signal_name,
                        signal_description=row.get("Signal Description"),
                        command_name=command_name,
                    )
                )
        return {**state, "comm_matrix_valid": signals}

    return node
