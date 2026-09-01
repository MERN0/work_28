"""Shared deterministic row-filtering logic used by comm_matrix_extract,
app_param_extract, io_signal_extract: keep exactly the rows whose
feature-column marker cell is a clean 'O' (`excel_io.is_marked_valid`, via
`InMemoryWorkbookStore.get_feature_marked_rows`). No LLM call - a marker
cell that isn't a clean O/x is simply not valid (see workbook_store.py's
`get_feature_marked_rows` for the diagnostic logging that keeps a
non-standard source file visible without needing a judgment call here)."""
from __future__ import annotations

from ..logging_utils import get_logger
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)


def extract_valid_rows(store: InMemoryWorkbookStore, sheet: str, feature_id: str) -> list[dict]:
    """Return raw row dicts (canonical field names, `_marker*` keys stripped)
    that are valid for `feature_id`: a clean 'O' marker."""
    rows = store.get_feature_marked_rows(sheet, feature_id)
    valid = [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows if row.get("_marker")]
    _logger.info("%s: %d row(s) total, %d valid", sheet, len(rows), len(valid))
    return valid
