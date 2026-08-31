"""Low-level, judgment-free Excel I/O helpers.

Everything here is mechanical: reading real cells honestly, locating header
rows/columns/sheets under typo/whitespace variance via fuzzy string matching,
and the deterministic O/x fast-path. None of this decides whether a row is
*semantically* valid - that's workbook_store.py / the agent nodes. This module
never invents a value that isn't literally present in a cell.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet
from rapidfuzz import fuzz, process


def load_workbook(path: str):
    return openpyxl.load_workbook(path, data_only=True, read_only=True)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def find_sheet(wb, *candidates: str, threshold: int = 80) -> Optional[Worksheet]:
    """Fuzzy-match a sheet name against `candidates`, tried in order."""
    names = wb.sheetnames
    norm_names = [_norm(n).lower() for n in names]
    for cand in candidates:
        norm_cand = _norm(cand).lower()
        if norm_cand in norm_names:
            return wb[names[norm_names.index(norm_cand)]]
        match = process.extractOne(norm_cand, norm_names, scorer=fuzz.token_sort_ratio)
        if match and match[1] >= threshold:
            return wb[names[norm_names.index(match[0])]]
    return None


def sheet_matrix(ws: Worksheet, max_rows: Optional[int] = None) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        rows.append(list(row))
        if max_rows and i + 1 >= max_rows:
            break
    return rows


def find_header_row(
    matrix: list[list[Any]],
    expected_anchors: list[str],
    max_scan_rows: int = 15,
    threshold: int = 75,
) -> Optional[int]:
    """Best-guess 0-based index of the header row, by fuzzy-matching cell text
    in each of the first `max_scan_rows` rows against `expected_anchors`
    (known column names for this sheet type). Handles title rows / merged
    banner rows sitting above the real header, common in these workbooks."""
    best_idx, best_score = None, 0
    for i, row in enumerate(matrix[:max_scan_rows]):
        cells = [_norm(c) for c in row if _norm(c)]
        if not cells:
            continue
        lowered = [c.lower() for c in cells]
        score = 0
        for anchor in expected_anchors:
            match = process.extractOne(anchor.lower(), lowered, scorer=fuzz.token_sort_ratio)
            if match and match[1] >= threshold:
                score += 1
        if score > best_score:
            best_score, best_idx = score, i
    return best_idx


def resolve_columns(headers: list[Any], candidate_names: list[str], threshold: int = 75) -> dict[str, Optional[int]]:
    """Map each of `candidate_names` to the best-matching column index in
    `headers`, or None if nothing crosses `threshold`."""
    norm_headers = [_norm(h).lower() for h in headers]
    result: dict[str, Optional[int]] = {}
    for cand in candidate_names:
        cand_l = cand.lower()
        if cand_l in norm_headers:
            result[cand] = norm_headers.index(cand_l)
            continue
        match = process.extractOne(cand_l, norm_headers, scorer=fuzz.token_sort_ratio)
        result[cand] = norm_headers.index(match[0]) if match and match[1] >= threshold else None
    return result


_FEATURE_ID_RE = re.compile(r"(\d{1,3})")


def normalize_feature_id(value: Any) -> Optional[str]:
    """Normalize a feature-id-ish value ('005', '5', ' Feature_005 ', 5) to a
    zero-padded 3-digit string, or None if it doesn't contain digits."""
    s = _norm(value)
    if not s:
        return None
    match = _FEATURE_ID_RE.search(s)
    if not match:
        return None
    return match.group(1).zfill(3)


def find_feature_column(headers: list[Any], feature_id: str) -> Optional[int]:
    """Locate the O/x marker column for `feature_id` among a Comm Matrix /
    App Parameter / IO Signal sheet's ~83 feature-number columns."""
    target = normalize_feature_id(feature_id)
    if target is None:
        return None
    for i, h in enumerate(headers):
        if normalize_feature_id(h) == target:
            return i
    return None


def is_marked_valid(cell_value: Any) -> Optional[bool]:
    """Deterministic fast-path for the O/x validity marker (per plan Decision 6).
    True for a clean 'O', False for a clean 'x'/'X' or a blank cell, None if the
    cell is anything else - callers escalate None cases to an LLM."""
    s = _norm(cell_value)
    if s == "":
        return False
    if s.upper() == "O":
        return True
    if s.upper() == "X":
        return False
    return None


def rows_as_dicts(
    matrix: list[list[Any]], header_row_idx: int, col_map: dict[str, Optional[int]]
) -> list[dict[str, Any]]:
    """Convert every non-blank data row below `header_row_idx` into a dict
    keyed by `col_map`'s keys, reading only real cell values."""
    out: list[dict[str, Any]] = []
    for row in matrix[header_row_idx + 1 :]:
        if all(_norm(c) == "" for c in row):
            continue
        record = {key: (row[idx] if idx is not None and idx < len(row) else None) for key, idx in col_map.items()}
        out.append(record)
    return out


def _fuzzy_key(value: Any) -> str:
    """Normalized form used only for fuzzy scoring: underscores treated as
    word separators too, so 'Config_Tol_Spd' and 'Config Tol Spd' score as
    near-identical regardless of which separator style was typed/read."""
    return _norm(value).lower().replace("_", " ")


def fuzzy_equal(a: Any, b: Any, threshold: int = 90) -> bool:
    na, nb = _fuzzy_key(a), _fuzzy_key(b)
    if not na or not nb:
        return na == nb
    if na == nb:
        return True
    return fuzz.token_sort_ratio(na, nb) >= threshold


def forward_fill_columns(matrix: list[list[Any]], col_indices: list[int]) -> None:
    """In-place forward-fill blank cells in `col_indices` from the last
    non-blank value above. Handles columns that are visually merged in Excel
    (openpyxl's default reader only returns a value on the merge's top-left
    cell; every other cell in the range reads as None) - e.g. Model Input
    Mapping's `Signal` column, which spans several `Test Case Input` rows."""
    last: dict[int, Any] = {idx: None for idx in col_indices}
    for row in matrix:
        for idx in col_indices:
            if idx >= len(row):
                continue
            if _norm(row[idx]) == "":
                row[idx] = last[idx]
            else:
                last[idx] = row[idx]


def leading_identifier(value: Any) -> str:
    """Extract the bare leading identifier token from a library-function
    signature or a generated step's call name - e.g. 'Lib_Ramp' from both
    'Lib_Ramp Signal_Name(Start=X,Stop=X,Step=X,Time=X)' (no space before the
    parameter list) and 'Lib_CheckTorqueLimit (Map=MapX,...)' (space before
    it). Splitting on whitespace *first*, before ever looking for '(', is
    what makes both stylings resolve to the same bare name. Splitting on '('
    alone (the earlier approach) kept the literal placeholder parameter name
    ('Signal_Name') as part of the extracted name for the no-space style,
    which made every real 'Lib_Ramp' usage fuzzy-score far below any sane
    threshold against the signature-derived candidate - silently failing the
    hallucination guardrail for every step that calls a library function."""
    s = _norm(value)
    if not s:
        return ""
    first_token = s.split()[0]
    return first_token.split("(")[0].strip()


def fuzzy_find(needle: Any, haystack: list[str], threshold: int = 90) -> Optional[str]:
    """Return the entry in `haystack` that best fuzzy-matches `needle`, or None
    if nothing crosses `threshold`. Used by the hallucination guardrail - the
    default is deliberately stricter than header/column matching (75-80,
    tuned separately at each of those call sites) because short domain codes
    that share a long common prefix (e.g. 'Config_Tol_Spd' vs
    'Config_Tol_rpm') can otherwise cross a lower threshold and let a
    hallucinated-but-similar name slip past as a real match."""
    n = _fuzzy_key(needle)
    if not n:
        return None
    keyed = [_fuzzy_key(h) for h in haystack]
    if n in keyed:
        return haystack[keyed.index(n)]
    match = process.extractOne(n, keyed, scorer=fuzz.token_sort_ratio)
    return haystack[keyed.index(match[0])] if match and match[1] >= threshold else None
