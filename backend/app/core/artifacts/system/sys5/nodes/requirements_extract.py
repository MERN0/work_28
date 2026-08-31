"""Hybrid node: classify each requirement-sheet row's Category. A clean
fuzzy match against the known vocabulary is resolved deterministically;
anything else escalates to an LLM (plan Decision 6).

Only "Functional Requirement" rows become testable Requirement objects;
"Heading"/"Information" rows are kept as queryable background context.
Other known categories (Configuration/NonFunctional/Security Requirement)
are recognized but not carried further, since only Functional Requirements
get test cases per the workflow spec.
"""
from __future__ import annotations

from pydantic import BaseModel

from .. import excel_io
from ..agents import run_agent_with_structured_output
from ..logging_utils import get_logger, stage_timer
from ..prompts import get_prompt
from ..schema import HeadingInfoRow, Requirement
from ..state import PipelineState
from ..workbook_store import InMemoryWorkbookStore

_logger = get_logger(__name__)

_KNOWN_CATEGORIES = [
    "Heading",
    "Information",
    "Configuration Requirement",
    "Functional Requirement",
    "NonFunctional Requirement",
    "Security Requirement",
]


class _ClassifiedRow(BaseModel):
    row_index: int
    category: str  # must be one of _KNOWN_CATEGORIES


class _ClassificationBatch(BaseModel):
    rows: list[_ClassifiedRow]


def _to_requirement(row: dict) -> Requirement:
    return Requirement(
        req_id=excel_io._norm(row.get("Requirement ID")),
        description=excel_io._norm(row.get("Requirement Description")),
        category="Functional Requirement",
        variant=excel_io._norm(row.get("Variant")) or None,
        priority=excel_io._norm(row.get("Priority")) or None,
        verification_method=excel_io._norm(row.get("Verification Method")) or None,
        verification_criteria=excel_io._norm(row.get("Verification Criteria")) or None,
        verification_stage=excel_io._norm(row.get("Verification Stage")) or None,
        source=excel_io._norm(row.get("Source")) or None,
        status=excel_io._norm(row.get("Status")) or None,
        release=excel_io._norm(row.get("Release")) or None,
        downstream_traceability=excel_io._norm(row.get("Downstream Traceability")) or None,
        remarks=excel_io._norm(row.get("Remarks")) or None,
    )


def build(store: InMemoryWorkbookStore, llm, tools: list, pipeline_config=None):
    threshold = pipeline_config.category_match_threshold if pipeline_config else 95

    def node(state: PipelineState) -> PipelineState:
        with stage_timer(_logger, "requirements_extract"):
            rows = store.get_requirement_rows()

            clean: list[tuple[dict, str]] = []
            ambiguous: list[tuple[int, dict]] = []
            for i, row in enumerate(rows):
                raw_category = row.get("Category")
                match = excel_io.fuzzy_find(raw_category, _KNOWN_CATEGORIES, threshold=threshold)
                if match:
                    clean.append((row, match))
                elif excel_io._norm(raw_category):
                    ambiguous.append((i, row))
                # a genuinely blank Category is dropped silently (not a row worth classifying)

            _logger.info("requirement sheet: %d row(s), %d classified via fast-path, %d ambiguous", len(rows), len(clean), len(ambiguous))

            if ambiguous:
                listing = "\n".join(
                    f"[{i}] Category={row.get('Category')!r} Requirement Description={row.get('Requirement Description')!r}"
                    for i, row in ambiguous
                )
                prompt = get_prompt("requirements_extract")
                user_input = (
                    "The following requirement-sheet rows have a Category value that didn't cleanly match "
                    f"one of: {_KNOWN_CATEGORIES}. Classify each into exactly one of those values.\n\n{listing}"
                )
                result, _ = run_agent_with_structured_output(
                    llm, tools, prompt, user_input, _ClassificationBatch, pipeline_config=pipeline_config
                )
                decided = {c.row_index: c.category for c in result.rows}
                for i, row in ambiguous:
                    category = decided.get(i)
                    if category in _KNOWN_CATEGORIES:
                        clean.append((row, category))

            requirements: list[Requirement] = []
            heading_info: list[HeadingInfoRow] = []
            for row, category in clean:
                if category == "Functional Requirement":
                    requirements.append(_to_requirement(row))
                elif category in ("Heading", "Information"):
                    heading_info.append(
                        HeadingInfoRow(
                            req_id=excel_io._norm(row.get("Requirement ID")) or None,
                            description=excel_io._norm(row.get("Requirement Description")),
                            category=category,
                        )
                    )
            _logger.info("requirements_extract: %d functional requirement(s), %d heading/info row(s)", len(requirements), len(heading_info))

        return {**state, "requirements": requirements, "heading_info": heading_info}

    return node
