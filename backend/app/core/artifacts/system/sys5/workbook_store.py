"""The "virtual backend": every input workbook is parsed from disk exactly
once into an InMemoryWorkbookStore. All agent tools and pipeline nodes query
this store instead of touching disk again - real disk I/O only happens once
here (loading) and once at the very end (writing the output workbooks).

Row *reading* here is purely mechanical (never invents/interprets a value).
Row *validity* (O/x, category classification) is left to callers: this store
exposes the raw marker/category text plus the excel_io fast-path helpers, and
callers (nodes) decide whether to trust the fast path or escalate to an LLM.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional

from . import excel_io
from .logging_utils import get_logger, stage_timer
from .pipeline_config import PipelineConfig
from .schema import (
    AbbreviationEntry,
    CommandListEntry,
    CompoundCommand,
    CompoundCommandStep,
    CustomKeywordEntry,
    LibraryEntry,
    ModelInputMappingRow,
    ToleranceEntry,
)

_logger = get_logger(__name__)

ROLE_HINTS: dict[str, list[str]] = {
    "requirements": ["System Requirements", "TE_TMHC_HILS Development & Testing_ System Requirements"],
    "command_list": ["TE_TMHC_Command_List"],
    "configuration": ["TE_TMHC_Configuration_File"],
    "compound_commands": ["TE_TMHC_Compound_Commands"],
    "keyword_library": [
        "TE_TMHC_HILLS_Development & Testing_Keyword_Library_Description_Sheet",
        "Keyword_Library_Description_Sheet",
    ],
}


class MissingInputFileError(RuntimeError):
    pass


def resolve_input_files(input_folder_path: str, req_filename: str, uploaded_files: list[str]) -> dict[str, str]:
    """Locate the 5 expected input workbooks among `uploaded_files` and/or
    `input_folder_path`, matching by exact `req_filename` for the requirements
    workbook and fuzzy basename matching for the other 4."""
    candidates: list[str] = list(uploaded_files or [])
    if input_folder_path and os.path.isdir(input_folder_path):
        for fname in os.listdir(input_folder_path):
            if fname.lower().endswith((".xlsx", ".xlsm")):
                candidates.append(os.path.join(input_folder_path, fname))
    candidates = sorted(set(candidates))
    if not candidates:
        raise MissingInputFileError(f"No input workbooks found under {input_folder_path!r} or uploaded_files")

    basenames = [os.path.splitext(os.path.basename(p))[0] for p in candidates]
    resolved: dict[str, str] = {}

    for path in candidates:
        if os.path.basename(path) == req_filename:
            resolved["requirements"] = path
            break

    for role, hints in ROLE_HINTS.items():
        if role in resolved:
            continue
        for hint in hints:
            match = excel_io.fuzzy_find(hint, basenames, threshold=70)
            if match:
                resolved[role] = candidates[basenames.index(match)]
                break

    missing = [role for role in ROLE_HINTS if role not in resolved]
    if missing:
        raise MissingInputFileError(f"Could not locate input workbook(s) for role(s): {missing} among {candidates}")
    return resolved


_COMPOUND_HEADER_RE = re.compile(r"^Compound\s+(.+)$", re.IGNORECASE)
_STEP_TABLE_HEADERS = ["Parameter Settings", "Units", "Expected Value", "Units", "Whether to execute the command", "Remarks"]


def _parse_compound_sheet(matrix: list[list[Any]], source_sheet: str) -> list[CompoundCommand]:
    """Parse a Compound Commands sheet: many stacked mini-tables, each opening
    with a 'Compound <name>' row and followed by its ordered steps until the
    next 'Compound <name>' row (or sheet end)."""
    commands: list[CompoundCommand] = []
    current_name: Optional[str] = None
    current_steps: list[CompoundCommandStep] = []
    col_map: dict[str, Optional[int]] = {}

    def flush() -> None:
        if current_name:
            commands.append(CompoundCommand(name=current_name, source_sheet=source_sheet, steps=list(current_steps)))

    for row in matrix:
        cells = [excel_io._norm(c) for c in row]
        if not any(cells):
            continue

        marker = None
        for cell in cells[:3]:
            m = _COMPOUND_HEADER_RE.match(cell)
            if m:
                marker = m.group(1)
                break
        if marker:
            flush()
            current_name, current_steps, col_map = marker, [], {}
            continue

        if current_name is None:
            continue

        resolved = excel_io.resolve_columns(cells, _STEP_TABLE_HEADERS, threshold=80)
        if sum(1 for v in resolved.values() if v is not None) >= 3:
            col_map = resolved
            continue

        keyword_cell_idx = next((i for i, c in enumerate(cells) if c), None)
        if keyword_cell_idx is None:
            continue
        step_text = cells[keyword_cell_idx]

        def _get(name: str) -> Optional[str]:
            idx = col_map.get(name)
            return cells[idx] if idx is not None and idx < len(cells) and cells[idx] else None

        current_steps.append(
            CompoundCommandStep(
                keyword_line=step_text,
                parameter_settings=_get("Parameter Settings"),
                units=cells[col_map["Units"]] if col_map.get("Units") is not None and col_map["Units"] < len(cells) and cells[col_map["Units"]] else None,
                expected_value=_get("Expected Value"),
                whether_execute=_get("Whether to execute the command"),
                remarks=_get("Remarks"),
            )
        )
    flush()
    return commands


@dataclass
class InMemoryWorkbookStore:
    file_paths: dict[str, str]
    pipeline_config: PipelineConfig = field(default_factory=PipelineConfig)

    feature_index: dict[str, dict[str, str]] = field(default_factory=dict)
    abbreviations: list[AbbreviationEntry] = field(default_factory=list)

    requirement_headers: list[Any] = field(default_factory=list)
    requirement_matrix: list[list[Any]] = field(default_factory=list)
    requirement_header_row: int = -1

    comm_matrix_headers: list[Any] = field(default_factory=list)
    comm_matrix_matrix: list[list[Any]] = field(default_factory=list)
    comm_matrix_header_row: int = -1

    app_param_headers: list[Any] = field(default_factory=list)
    app_param_matrix: list[list[Any]] = field(default_factory=list)
    app_param_header_row: int = -1

    io_signal_headers: list[Any] = field(default_factory=list)
    io_signal_matrix: list[list[Any]] = field(default_factory=list)
    io_signal_header_row: int = -1

    command_list: list[CommandListEntry] = field(default_factory=list)
    tolerances: list[ToleranceEntry] = field(default_factory=list)
    model_input_mapping: list[ModelInputMappingRow] = field(default_factory=list)
    compound_commands: dict[str, CompoundCommand] = field(default_factory=dict)
    library_entries: list[LibraryEntry] = field(default_factory=list)
    custom_keywords: list[CustomKeywordEntry] = field(default_factory=list)

    @classmethod
    def load(
        cls, file_paths: dict[str, str], req_sheet_name: str, pipeline_config: Optional[PipelineConfig] = None
    ) -> "InMemoryWorkbookStore":
        store = cls(file_paths=file_paths, pipeline_config=pipeline_config or PipelineConfig())
        with stage_timer(_logger, "load_inputs: requirements workbook"):
            store._load_requirements_workbook(req_sheet_name)
        with stage_timer(_logger, "load_inputs: command list"):
            store._load_command_list()
        with stage_timer(_logger, "load_inputs: configuration (tolerances/model input mapping)"):
            store._load_configuration()
        with stage_timer(_logger, "load_inputs: compound commands"):
            store._load_compound_commands()
        with stage_timer(_logger, "load_inputs: keyword/library"):
            store._load_keyword_library()
        _logger.info(
            "workbook store loaded: %d requirement row(s), %d comm-matrix row(s), %d command(s), "
            "%d tolerance(s), %d model-input-mapping row(s), %d compound command(s), %d library entrie(s)",
            max(len(store.requirement_matrix) - 1, 0),
            max(len(store.comm_matrix_matrix) - 1, 0),
            len(store.command_list),
            len(store.tolerances),
            len(store.model_input_mapping),
            len(store.compound_commands),
            len(store.library_entries),
        )
        return store

    # -- Threshold-aware wrappers (source from self.pipeline_config) --------

    def _find_sheet(self, wb, *candidates: str):
        return excel_io.find_sheet(wb, *candidates, threshold=self.pipeline_config.sheet_name_match_threshold)

    def _find_header_row(self, matrix: list[list[Any]], anchors: list[str]):
        return excel_io.find_header_row(matrix, anchors, threshold=self.pipeline_config.header_row_match_threshold)

    def _resolve_columns(self, headers: list[Any], candidates: list[str]) -> dict[str, Optional[int]]:
        return excel_io.resolve_columns(headers, candidates, threshold=self.pipeline_config.column_match_threshold)

    # -- Requirements workbook -------------------------------------------------

    def _load_requirements_workbook(self, req_sheet_name: str) -> None:
        wb = excel_io.load_workbook(self.file_paths["requirements"])

        index_ws = self._find_sheet(wb, "Index")
        if index_ws is not None:
            matrix = excel_io.sheet_matrix(index_ws)
            header_row = self._find_header_row(matrix, ["Feature ID Link", "Feature Name", "Function Group"])
            if header_row is not None:
                col_map = self._resolve_columns(matrix[header_row], ["Feature ID Link", "Feature Name", "Function Group"])
                for row in excel_io.rows_as_dicts(matrix, header_row, col_map):
                    fid = excel_io.normalize_feature_id(row.get("Feature ID Link"))
                    if fid:
                        self.feature_index[fid] = {
                            "name": excel_io._norm(row.get("Feature Name")),
                            "function_group": excel_io._norm(row.get("Function Group")),
                        }

        abbr_ws = self._find_sheet(wb, "Master List Abbreviations", "Master List - Abbreviations")
        if abbr_ws is not None:
            matrix = excel_io.sheet_matrix(abbr_ws)
            header_row = self._find_header_row(matrix, ["Abbreviations", "Description/Definition"])
            if header_row is not None:
                col_map = self._resolve_columns(matrix[header_row], ["Abbreviations", "Description/Definition"])
                for row in excel_io.rows_as_dicts(matrix, header_row, col_map):
                    abbr = excel_io._norm(row.get("Abbreviations"))
                    if abbr:
                        self.abbreviations.append(
                            AbbreviationEntry(abbreviation=abbr, definition=excel_io._norm(row.get("Description/Definition")))
                        )

        req_ws = self._find_sheet(wb, req_sheet_name)
        if req_ws is not None:
            self.requirement_matrix = excel_io.sheet_matrix(req_ws)
            self.requirement_header_row = self._find_header_row(
                self.requirement_matrix, ["Requirement ID", "Requirement Description", "Category"]
            ) or 0
            self.requirement_headers = self.requirement_matrix[self.requirement_header_row]

        comm_ws = self._find_sheet(wb, "Master Comm Matrix (CAN)", "Master Comm Matrix")
        if comm_ws is not None:
            self.comm_matrix_matrix = excel_io.sheet_matrix(comm_ws)
            self.comm_matrix_header_row = self._find_header_row(
                self.comm_matrix_matrix, ["Signal ID", "Signal name", "Message Name"]
            ) or 0
            self.comm_matrix_headers = self.comm_matrix_matrix[self.comm_matrix_header_row]

        param_ws = self._find_sheet(wb, "Master List - App Parameter", "Master List App Parameter")
        if param_ws is not None:
            self.app_param_matrix = excel_io.sheet_matrix(param_ws)
            self.app_param_header_row = self._find_header_row(
                self.app_param_matrix, ["Parameter ID", "Parameter Name", "Parameter Type"]
            ) or 0
            self.app_param_headers = self.app_param_matrix[self.app_param_header_row]

        io_ws = self._find_sheet(wb, "Master Input Output Signals")
        if io_ws is not None:
            self.io_signal_matrix = excel_io.sheet_matrix(io_ws)
            self.io_signal_header_row = self._find_header_row(
                self.io_signal_matrix, ["Signal ID", "Logical Signal Name", "Signal Type"]
            ) or 0
            self.io_signal_headers = self.io_signal_matrix[self.io_signal_header_row]

    # -- Command List / Configuration workbooks --------------------------------

    def _load_command_list(self) -> None:
        wb = excel_io.load_workbook(self.file_paths["command_list"])
        ws = self._find_sheet(wb, "Command List")
        if ws is None:
            return
        matrix = excel_io.sheet_matrix(ws)
        header_row = self._find_header_row(matrix, ["Command name", "Signal Name", "Message Name"])
        if header_row is None:
            return
        col_map = self._resolve_columns(
            matrix[header_row], ["Type", "Command name", "Message Name", "Signal Description", "Signal Name"]
        )
        for row in excel_io.rows_as_dicts(matrix, header_row, col_map):
            name = excel_io._norm(row.get("Command name"))
            if not name:
                continue
            self.command_list.append(
                CommandListEntry(
                    type=excel_io._norm(row.get("Type")) or None,
                    command_name=name,
                    message_name=excel_io._norm(row.get("Message Name")) or None,
                    signal_description=excel_io._norm(row.get("Signal Description")) or None,
                    signal_name=excel_io._norm(row.get("Signal Name")) or None,
                )
            )

    def _load_configuration(self) -> None:
        wb = excel_io.load_workbook(self.file_paths["configuration"])

        tol_ws = self._find_sheet(wb, "Tolerances")
        if tol_ws is not None:
            matrix = excel_io.sheet_matrix(tol_ws)
            header_row = self._find_header_row(matrix, ["Tolerance Configuration", "Value (+,-)", "Tolerance Unit"])
            if header_row is not None:
                col_map = self._resolve_columns(
                    matrix[header_row],
                    ["Tolerance Configuration", "Description", "Unit", "Value (+,-)", "Tolerance Unit", "Remarks"],
                )
                for row in excel_io.rows_as_dicts(matrix, header_row, col_map):
                    name = excel_io._norm(row.get("Tolerance Configuration"))
                    if not name:
                        continue
                    value = excel_io._norm(row.get("Value (+,-)"))
                    pos, _, neg = value.partition(",")
                    self.tolerances.append(
                        ToleranceEntry(
                            tolerance_configuration=name,
                            description=excel_io._norm(row.get("Description")) or None,
                            unit=excel_io._norm(row.get("Unit")) or None,
                            value_positive=pos.strip() or None,
                            value_negative=neg.strip() or None,
                            tolerance_unit=excel_io._norm(row.get("Tolerance Unit")) or None,
                            remarks=excel_io._norm(row.get("Remarks")) or None,
                        )
                    )

        mim_ws = self._find_sheet(wb, "Model_Input_Mapping", "Model Input Mapping")
        if mim_ws is not None:
            matrix = excel_io.sheet_matrix(mim_ws)
            header_row = self._find_header_row(matrix, ["Signal", "Test Case Input", "Model Input"])
            if header_row is not None:
                col_map = self._resolve_columns(
                    matrix[header_row], ["Signal", "Test Case Input", "Model Input", "Model Output to ECU", "Remark"]
                )
                data_rows = matrix[header_row + 1 :]
                signal_idx = col_map.get("Signal")
                if signal_idx is not None:
                    excel_io.forward_fill_columns(data_rows, [signal_idx])
                for row in excel_io.rows_as_dicts(data_rows, -1, col_map):
                    signal = excel_io._norm(row.get("Signal"))
                    if not signal or excel_io._norm(row.get("Test Case Input")) == "":
                        continue
                    self.model_input_mapping.append(
                        ModelInputMappingRow(
                            signal=signal,
                            test_case_input=excel_io._norm(row.get("Test Case Input")) or None,
                            model_input=excel_io._norm(row.get("Model Input")) or None,
                            model_output_to_ecu=excel_io._norm(row.get("Model Output to ECU")) or None,
                            remark=excel_io._norm(row.get("Remark")) or None,
                        )
                    )

    # -- Compound Commands / Keyword-Library workbooks -------------------------

    def _load_compound_commands(self) -> None:
        wb = excel_io.load_workbook(self.file_paths["compound_commands"])
        for sheet_label, source in (("Compound Commands (Set)", "Set"), ("Compound Commands (Verify)", "Verify")):
            ws = self._find_sheet(wb, sheet_label)
            if ws is None:
                continue
            for cmd in _parse_compound_sheet(excel_io.sheet_matrix(ws), source):
                self.compound_commands[cmd.name] = cmd

    def _load_keyword_library(self) -> None:
        wb = excel_io.load_workbook(self.file_paths["keyword_library"])

        lib_ws = self._find_sheet(wb, "Library List")
        if lib_ws is not None:
            matrix = excel_io.sheet_matrix(lib_ws)
            header_row = self._find_header_row(matrix, ["Library", "Library Description", "Example Usage"])
            if header_row is not None:
                col_map = self._resolve_columns(matrix[header_row], ["Library", "Library Description", "Example Usage"])
                for row in excel_io.rows_as_dicts(matrix, header_row, col_map):
                    sig = excel_io._norm(row.get("Library"))
                    if not sig:
                        continue
                    self.library_entries.append(
                        LibraryEntry(
                            signature=sig,
                            description=excel_io._norm(row.get("Library Description")) or None,
                            example_usage=excel_io._norm(row.get("Example Usage")) or None,
                        )
                    )

        kw_ws = self._find_sheet(wb, "Custom Keyword&Library Details", "Custom Keyword & Library Details")
        if kw_ws is not None:
            matrix = excel_io.sheet_matrix(kw_ws)
            header_row = self._find_header_row(matrix, ["Format", "Logical Formula / Method", "Example Reference"])
            if header_row is not None:
                col_map = self._resolve_columns(
                    matrix[header_row], ["Format", "Type", "Logical Formula / Method", "Example Reference"]
                )
                for row in excel_io.rows_as_dicts(matrix, header_row, col_map):
                    fmt = excel_io._norm(row.get("Format"))
                    if not fmt:
                        continue
                    self.custom_keywords.append(
                        CustomKeywordEntry(
                            format=fmt,
                            type=excel_io._norm(row.get("Type")) or None,
                            logical_formula=excel_io._norm(row.get("Logical Formula / Method")) or None,
                            example=excel_io._norm(row.get("Example Reference")) or None,
                        )
                    )

    # -- Query helpers -----------------------------------------------------

    def get_feature_info(self, feature_id: str) -> Optional[dict[str, str]]:
        return self.feature_index.get(excel_io.normalize_feature_id(feature_id) or feature_id)

    def get_glossary_text(self) -> str:
        return "\n".join(f"{a.abbreviation}: {a.definition}" for a in self.abbreviations)

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

    _SHEET_FIELD_CANDIDATES: ClassVar[dict[str, list[str]]] = {
        "comm_matrix": [
            "Signal ID", "Message Name", "Message IDs", "Logical Signal Name", "Signal name",
            "Signal Description", "Message DLC", "Periodicity", "Length", "Bit Positions (0 to 63)",
            "Resolution", "Physical Range", "Integer Range", "Unit", "Default Value", "Start up Value",
            "Message_Send Type", "ECU HW (Transmitting)", "ECU HW (Receiving)", "Remarks",
        ],
        "app_param": [
            "Parameter ID", "Parameter Name", "Parameter Description", "Parameter Type", "Unit",
            "Parameter Valid Value", "Parameter default value", "Parameter min Value", "Parameter max Value",
            "Resolution", "Interdependency with other parameters", "Linked System requirements", "Variant",
            "Change by EOL?", "Change by Service?", "Access Conditions", "Remarks",
        ],
        "io_signal": [
            "Signal ID", "Logical Signal Name", "Signal Type", "Variants", "ECU", "Input/Output",
            "Maximum Rated Voltage(V)", "Nominal Operating current(mA)", "Minimum Rated Voltage(V)", "Remarks",
        ],
    }

    def get_feature_marked_rows(self, sheet: str, feature_id: str) -> list[dict[str, Any]]:
        """Return every row of `sheet` ('comm_matrix' | 'app_param' | 'io_signal')
        keyed by canonical field names (fuzzy-resolved against the sheet's real
        headers), annotated with a `_marker` field: True/False from the
        deterministic O/x fast-path, or None if the cell needs LLM escalation
        (Decision 6)."""
        headers, matrix, header_row = {
            "comm_matrix": (self.comm_matrix_headers, self.comm_matrix_matrix, self.comm_matrix_header_row),
            "app_param": (self.app_param_headers, self.app_param_matrix, self.app_param_header_row),
            "io_signal": (self.io_signal_headers, self.io_signal_matrix, self.io_signal_header_row),
        }[sheet]
        col_idx = excel_io.find_feature_column(headers, feature_id)
        if col_idx is None:
            return []
        col_map = self._resolve_columns(headers, self._SHEET_FIELD_CANDIDATES[sheet])
        rows = excel_io.rows_as_dicts(matrix, header_row, col_map)
        for i, row in enumerate(rows):
            raw_row = matrix[header_row + 1 + i]
            marker_cell = raw_row[col_idx] if col_idx < len(raw_row) else None
            row["_marker"] = excel_io.is_marked_valid(marker_cell)
            row["_marker_raw"] = marker_cell
        return rows

    def lookup_command_name(self, signal_name: str, top_k: Optional[int] = None) -> list[dict[str, Any]]:
        top_k = top_k or self.pipeline_config.command_lookup_top_k
        results = []
        for entry in self.command_list:
            score = 0
            if entry.signal_name and excel_io.fuzzy_equal(entry.signal_name, signal_name, threshold=0):
                from rapidfuzz import fuzz

                score = fuzz.token_sort_ratio(excel_io._norm(entry.signal_name).lower(), excel_io._norm(signal_name).lower())
            if score:
                results.append({"command_name": entry.command_name, "signal_name": entry.signal_name, "score": score})
        results.sort(key=lambda r: -r["score"])
        return results[:top_k]

    def get_tolerance(self, name: str) -> Optional[ToleranceEntry]:
        names = [t.tolerance_configuration for t in self.tolerances]
        match = excel_io.fuzzy_find(name, names, threshold=self.pipeline_config.general_fuzzy_threshold)
        if not match:
            return None
        return next(t for t in self.tolerances if t.tolerance_configuration == match)

    def get_model_input_mapping(self, signal: str) -> list[ModelInputMappingRow]:
        signals = sorted({m.signal for m in self.model_input_mapping})
        match = excel_io.fuzzy_find(signal, signals, threshold=self.pipeline_config.model_input_match_threshold)
        if not match:
            return []
        return [m for m in self.model_input_mapping if m.signal == match]

    def search_compound_commands(self, query: str, top_k: Optional[int] = None) -> list[dict[str, Any]]:
        from rapidfuzz import fuzz

        top_k = top_k or self.pipeline_config.compound_command_shortlist_size
        scored = []
        for name, cmd in self.compound_commands.items():
            text = name + " " + " ".join(s.keyword_line for s in cmd.steps)
            score = fuzz.token_set_ratio(query.lower(), text.lower())
            scored.append({"name": name, "source_sheet": cmd.source_sheet, "score": score, "step_count": len(cmd.steps)})
        scored.sort(key=lambda r: -r["score"])
        return scored[:top_k]

    def get_compound_command(self, name: str) -> Optional[CompoundCommand]:
        if name in self.compound_commands:
            return self.compound_commands[name]
        match = excel_io.fuzzy_find(name, list(self.compound_commands.keys()), threshold=self.pipeline_config.general_fuzzy_threshold)
        return self.compound_commands.get(match) if match else None

    def search_library(self, query: str, top_k: Optional[int] = None) -> list[dict[str, Any]]:
        from rapidfuzz import fuzz

        top_k = top_k or self.pipeline_config.library_shortlist_size
        scored = []
        for entry in self.library_entries:
            text = entry.signature + " " + (entry.description or "")
            score = fuzz.token_set_ratio(query.lower(), text.lower())
            scored.append({"signature": entry.signature, "description": entry.description, "score": score})
        scored.sort(key=lambda r: -r["score"])
        return scored[:top_k]

    def exists(self, ref_kind: str, target_ref: Optional[str], fuzzy_threshold: Optional[int] = None) -> bool:
        """Hallucination guardrail: does `target_ref` literally exist (fuzzy
        matched) in the parsed source data for the given `ref_kind`?"""
        fuzzy_threshold = fuzzy_threshold or self.pipeline_config.hallucination_match_threshold
        if ref_kind == "none":
            return True
        if not target_ref:
            return False
        if ref_kind == "signal":
            candidates = [m.signal for m in self.model_input_mapping]
            candidates += [row.get("Signal name") or row.get("Signal Name") or "" for row in self._all_signal_rows()]
            candidates += [row.get("Signal ID") or "" for row in self._all_signal_rows()]
            candidates += [row.get("Logical Signal Name") or "" for row in self._all_signal_rows()]
        elif ref_kind == "command":
            candidates = [c.command_name for c in self.command_list]
        elif ref_kind == "compound_command":
            candidates = list(self.compound_commands.keys())
        elif ref_kind == "tolerance":
            candidates = [t.tolerance_configuration for t in self.tolerances]
        elif ref_kind == "library_call":
            candidates = [entry.signature.split("(")[0].strip() for entry in self.library_entries]
        elif ref_kind == "parameter":
            candidates = [row.get("Parameter Name") or "" for row in self._all_param_rows()]
        else:
            return False
        candidates = [c for c in candidates if c]
        return excel_io.fuzzy_find(target_ref, candidates, threshold=fuzzy_threshold) is not None

    def _all_signal_rows(self) -> list[dict[str, Any]]:
        col_map = self._resolve_columns(self.comm_matrix_headers, ["Signal ID", "Signal name", "Logical Signal Name"])
        rows = excel_io.rows_as_dicts(self.comm_matrix_matrix, self.comm_matrix_header_row, col_map)
        col_map2 = self._resolve_columns(self.io_signal_headers, ["Signal ID", "Logical Signal Name"])
        rows += excel_io.rows_as_dicts(self.io_signal_matrix, self.io_signal_header_row, col_map2)
        return rows

    def _all_param_rows(self) -> list[dict[str, Any]]:
        col_map = self._resolve_columns(self.app_param_headers, ["Parameter Name"])
        return excel_io.rows_as_dicts(self.app_param_matrix, self.app_param_header_row, col_map)
