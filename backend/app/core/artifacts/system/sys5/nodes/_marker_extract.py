"""Shared hybrid deterministic-fast-path + LLM-escalation logic (plan
Decision 6), used by comm_matrix_extract, app_param_extract, io_signal_extract.
"""
from __future__ import annotations

from pydantic import BaseModel

from ..agents import run_agent_with_structured_output
from ..prompts import get_prompt
from ..workbook_store import InMemoryWorkbookStore


class _AmbiguousDecision(BaseModel):
    row_index: int
    valid: bool


class _AmbiguousBatch(BaseModel):
    decisions: list[_AmbiguousDecision]


def extract_valid_rows(store: InMemoryWorkbookStore, sheet: str, feature_id: str, llm, tools: list) -> list[dict]:
    """Return raw row dicts (canonical field names, `_marker*` keys stripped)
    that are valid for `feature_id`: a clean 'O' via the deterministic
    fast-path, or an LLM-adjudicated True for anything ambiguous."""
    rows = store.get_feature_marked_rows(sheet, feature_id)
    valid: list[dict] = []
    ambiguous: list[tuple[int, object, dict]] = []
    for i, row in enumerate(rows):
        clean = {k: v for k, v in row.items() if not k.startswith("_")}
        marker = row.get("_marker")
        if marker is True:
            valid.append(clean)
        elif marker is None:
            ambiguous.append((i, row.get("_marker_raw"), clean))

    if ambiguous:
        listing = "\n".join(f"[{i}] marker_cell_content={raw!r} row={clean}" for i, raw, clean in ambiguous)
        prompt = get_prompt("marker_escalate")
        user_input = (
            f"Sheet: {sheet}\nFeature id: {feature_id}\n\n"
            f"For each row below, the feature-column marker cell was not a clean 'O' or 'x'. "
            f"Decide VALID or NOT for each.\n\n{listing}"
        )
        result, _ = run_agent_with_structured_output(llm, tools, prompt, user_input, _AmbiguousBatch)
        decided = {d.row_index: d.valid for d in result.decisions}
        for i, raw, clean in ambiguous:
            if decided.get(i):
                valid.append(clean)
    return valid
