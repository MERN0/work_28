"""Deterministic node: valid App Parameter rows for this feature."""
from __future__ import annotations

from .. import excel_io
from ._marker_extract import extract_valid_rows
from ..logging_utils import get_logger, stage_timer
from ..schema import AppParameter
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


def _s(row: dict, key: str) -> str | None:
    """Normalize a raw cell value to str|None before it reaches a pydantic
    model - `get_feature_marked_rows` returns whatever openpyxl read
    (int/float/datetime for a numeric-looking cell like a parameter's
    default value), and AppParameter's fields are plain `str`, which
    pydantic v2 does not coerce non-str input into."""
    return excel_io._norm(row.get(key)) or None


def build(store: InMemoryWorkbookStore, pipeline_config=None):
    def node(state: PipelineState) -> PipelineState:
        feature_id = state["feature_id"]
        with stage_timer(_logger, "app_param_extract", feature_id=feature_id):
            rows = extract_valid_rows(store, "app_param", feature_id)
            params = [
                AppParameter(
                    parameter_id=_s(row, "Parameter ID"),
                    parameter_name=_s(row, "Parameter Name"),
                    parameter_description=_s(row, "Parameter Description"),
                    parameter_type=_s(row, "Parameter Type"),
                    unit=_s(row, "Unit"),
                    valid_value=_s(row, "Parameter Valid Value"),
                    default_value=_s(row, "Parameter default value"),
                    min_value=_s(row, "Parameter min Value"),
                    max_value=_s(row, "Parameter max Value"),
                    resolution=_s(row, "Resolution"),
                )
                for row in rows
            ]
        return {**state, "app_param_valid": params}

    return node
