"""Pydantic data contracts shared across the SYS5 pipeline.

These models are the boundary between "raw cells read off a workbook" and
"structured data an LLM agent reasons over". Nothing here enforces
business-vocabulary correctness (e.g. Priority isn't an enum) because source
sheets are known to carry typos/whitespace variance (see excel_io.py's fuzzy
matching) - only structural shape is enforced.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

# --------------------------------------------------------------------------
# Requirements sheet
# --------------------------------------------------------------------------

class Requirement(BaseModel):
    req_id: str
    description: str
    category: str
    variant: Optional[str] = None
    priority: Optional[str] = None
    verification_method: Optional[str] = None
    verification_criteria: Optional[str] = None
    verification_stage: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    release: Optional[str] = None
    downstream_traceability: Optional[str] = None
    remarks: Optional[str] = None


class HeadingInfoRow(BaseModel):
    """A Heading/Information-category row from a requirement sheet, kept as
    queryable context (not turned into a test pattern)."""
    req_id: Optional[str] = None
    description: str
    category: str


def format_heading_info(rows: list["HeadingInfoRow"]) -> str:
    """Render Heading/Information rows as plain text for inclusion in an LLM
    prompt (see nodes/test_pattern_gen.py) - this is the "queryable ...
    context" HeadingInfoRow's own docstring promises; without a caller
    formatting and including it somewhere, the rows would be collected for
    nothing. Returns "" for an empty list so callers can splice it into an
    f-string unconditionally."""
    if not rows:
        return ""
    return "\n".join(f"- [{r.category}]{f' ({r.req_id})' if r.req_id else ''} {r.description}" for r in rows)


# --------------------------------------------------------------------------
# Factors (human-supplied domain knowledge, see factors.py)
# --------------------------------------------------------------------------

class Factor(BaseModel):
    name: str
    values: list[str]
    ease_of_adjustment: Optional[str] = None
    signal_ref: Optional[str] = None  # explicit Model_Input_Mapping "Signal" this factor sets, if known


class FactorTable(BaseModel):
    feature_id: str
    fixed_factors: list[Factor]
    variable_factors: list[Factor]


# --------------------------------------------------------------------------
# Test Pattern
# --------------------------------------------------------------------------

class TestPatternRow(BaseModel):
    test_case_no: int
    scenario_id: str
    fixed_values: dict[str, str]     # factor name -> value, for this row
    variable_transitions: dict[str, str]  # factor name -> "A -> B" transition text
