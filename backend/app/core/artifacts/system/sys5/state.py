"""LangGraph state schema.

The InMemoryWorkbookStore is deliberately NOT a state field - it's injected
into node closures by the graph builder instead (see graph.py), so it never
needs to flow through (and never risks being serialized by) LangGraph state
handling. No checkpointer is wired up: generate() is a single synchronous
call with no pause/resume requirement, so state can stay a plain in-process
object.
"""
from __future__ import annotations

from typing import TypedDict

from .schema import HeadingInfoRow, Requirement, TestPatternRow


class PipelineState(TypedDict, total=False):
    feature_id: str
    feature_name: str
    function_group: str

    requirements: list[Requirement]
    heading_info: list[HeadingInfoRow]

    test_patterns: dict[str, list[TestPatternRow]]  # req_id -> pattern rows
