"""Deterministic node: classify each requirement-sheet row's Category via a
fuzzy match against the known vocabulary. Only a row whose Category crosses
`category_match_threshold` gets classified; anything else (a typo too far
off, or a genuinely different value) is dropped rather than guessed - same
treatment a blank Category already got.

Only "Functional Requirement" rows become testable Requirement objects;
"Heading"/"Information" rows are kept as queryable background context.
Other known categories (Configuration/NonFunctional/Security Requirement)
are recognized but not carried further, since only Functional Requirements
get test cases per the workflow spec.
"""
from __future__ import annotations

from .. import excel_io
from ..logging_utils import get_logger, stage_timer
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


def build(store: InMemoryWorkbookStore, pipeline_config=None):
    threshold = pipeline_config.category_match_threshold if pipeline_config else 95

    def node(state: PipelineState) -> PipelineState:
        with stage_timer(_logger, "requirements_extract"):
            rows = store.get_requirement_rows()

            classified: list[tuple[dict, str]] = []
            dropped = 0
            for row in rows:
                raw_category = row.get("Category")
                match = excel_io.fuzzy_find(raw_category, _KNOWN_CATEGORIES, threshold=threshold)
                if match:
                    classified.append((row, match))
                elif excel_io._norm(raw_category):
                    dropped += 1
                # a genuinely blank Category is dropped silently (not a row worth classifying)

            if dropped:
                _logger.warning(
                    "requirements_extract: %d row(s) had a Category value that didn't match any known category "
                    "(threshold=%d) and were dropped rather than guessed", dropped, threshold,
                )
            _logger.info("requirement sheet: %d row(s), %d classified, %d dropped", len(rows), len(classified), dropped)

            requirements: list[Requirement] = []
            heading_info: list[HeadingInfoRow] = []
            for row, category in classified:
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
