"""The "virtual backend": the System Requirements workbook is parsed from
disk exactly once into an InMemoryWorkbookStore. The node layer queries this
store instead of touching disk again.

Row *reading* here is purely mechanical (never invents/interprets a value).
Row *validity* (Category classification) is left to callers: this store
exposes the raw category text plus the excel_io fast-path helpers, and
callers (nodes) apply those deterministically - no LLM involved in deciding
what a row means.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from . import excel_io
from .logging_utils import get_logger, stage_timer
from .pipeline_config import PipelineConfig

_logger = get_logger(__name__)


class MissingInputFileError(RuntimeError):
    pass


def resolve_requirements_file(input_folder_path: str, req_filename: str, uploaded_files: list[str]) -> str:
    """Locate the System Requirements workbook among `uploaded_files` and/or
    `input_folder_path`: an exact `req_filename` basename match, or (if
    there's exactly one .xlsx/.xlsm candidate) that one file."""
    candidates: list[str] = list(uploaded_files or [])
    if input_folder_path and os.path.isdir(input_folder_path):
        for fname in os.listdir(input_folder_path):
            if fname.lower().endswith((".xlsx", ".xlsm")):
                candidates.append(os.path.join(input_folder_path, fname))
    candidates = sorted(set(candidates))
    if not candidates:
        raise MissingInputFileError(f"No requirements workbook found under {input_folder_path!r} or uploaded_files")

    if req_filename:
        for path in candidates:
            if os.path.basename(path) == req_filename:
                return path

    if len(candidates) == 1:
        return candidates[0]

    raise MissingInputFileError(
        f"Could not identify the requirements workbook among {candidates} - pass the requirements file "
        f"explicitly, or ensure req_filename ({req_filename!r}) matches exactly one candidate's basename."
    )


@dataclass
class InMemoryWorkbookStore:
    file_path: str
    pipeline_config: PipelineConfig = field(default_factory=PipelineConfig)

    feature_index: dict[str, dict[str, str]] = field(default_factory=dict)

    requirement_headers: list[Any] = field(default_factory=list)
    requirement_matrix: list[list[Any]] = field(default_factory=list)
    requirement_header_row: int = -1

    @classmethod
    def load(
        cls, file_path: str, req_sheet_name: str, pipeline_config: Optional[PipelineConfig] = None
    ) -> "InMemoryWorkbookStore":
        store = cls(file_path=file_path, pipeline_config=pipeline_config or PipelineConfig())
        with stage_timer(_logger, "load_inputs: requirements workbook"):
            store._load_requirements_workbook(req_sheet_name)
        _logger.info(
            "workbook store loaded: %d requirement row(s) for sheet %r",
            max(len(store.requirement_matrix) - 1, 0), req_sheet_name,
        )
        return store

    # -- Threshold-aware wrappers (source from self.pipeline_config) --------

    def _find_sheet(self, wb, *candidates: str):
        return excel_io.find_sheet(wb, *candidates, threshold=self.pipeline_config.sheet_name_match_threshold)

    def _find_header_row(self, matrix: list[list[Any]], anchors: list[str]):
        return excel_io.find_header_row(matrix, anchors, threshold=self.pipeline_config.header_row_match_threshold)

    def _resolve_columns(self, headers: list[Any], candidates: list[str]) -> dict[str, Optional[int]]:
        return excel_io.resolve_columns(headers, candidates, threshold=self.pipeline_config.column_match_threshold)

    def _load_sheet(
        self, wb, candidates: list[str], anchors: list[str]
    ) -> Optional[tuple[list[list[Any]], int, list[Any]]]:
        """Find a sheet by name (fuzzy) and its header row (fuzzy, falling
        back to row 0 if nothing scores well against `anchors`). Returns
        `(matrix, header_row_index, header_row_values)`, or `None` only if
        the sheet itself isn't found at all."""
        ws = self._find_sheet(wb, *candidates)
        if ws is None:
            return None
        matrix = excel_io.sheet_matrix(ws)
        header_row = self._find_header_row(matrix, anchors) or 0
        headers = matrix[header_row] if header_row < len(matrix) else []
        return matrix, header_row, headers

    # -- Requirements workbook -------------------------------------------------

    def _load_requirements_workbook(self, req_sheet_name: str) -> None:
        wb = excel_io.load_workbook(self.file_path)

        loaded = self._load_sheet(wb, ["Index"], ["Feature ID Link", "Feature Name", "Function Group"])
        if loaded:
            matrix, header_row, headers = loaded
            col_map = self._resolve_columns(headers, ["Feature ID Link", "Feature Name", "Function Group"])
            for row in excel_io.rows_as_dicts(matrix, header_row, col_map):
                fid = excel_io.normalize_feature_id(row.get("Feature ID Link"))
                if fid:
                    self.feature_index[fid] = {
                        "name": excel_io._norm(row.get("Feature Name")),
                        "function_group": excel_io._norm(row.get("Function Group")),
                    }

        loaded = self._load_sheet(wb, [req_sheet_name], ["Requirement ID", "Requirement Description", "Category"])
        if loaded:
            self.requirement_matrix, self.requirement_header_row, self.requirement_headers = loaded

    # -- Query helpers -----------------------------------------------------

    def get_feature_info(self, feature_id: str) -> Optional[dict[str, str]]:
        return self.feature_index.get(excel_io.normalize_feature_id(feature_id) or feature_id)

    def get_requirement_rows(self) -> list[dict[str, Any]]:
        col_map = self._resolve_columns(
            self.requirement_headers,
            [
                "Requirement ID", "Requirement Description", "Category", "Variant", "Priority",
                "Verification Method", "Verification Criteria", "Verification Stage", "Source",
                "Status", "Release", "Downstream Traceability", "Remarks",
            ],
        )
        return excel_io.rows_as_dicts(self.requirement_matrix, self.requirement_header_row, col_map)
