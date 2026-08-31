"""Agent-facing tools: thin, read-only wrappers around an `InMemoryWorkbookStore`
instance. Built per pipeline run via `build_tools(store)` so each run's agents
query that run's own parsed data, never global state.

These tools are the *only* way an agent sees source data - they never
fabricate or complete a value, they only ever return what was literally
parsed off a sheet (see workbook_store.py / excel_io.py).

## Why `StructuredTool.from_function` and not the `@tool` decorator

LangChain's docs recommend `@tool` as "the simplest way to create a tool"
(https://docs.langchain.com/oss/python/langchain/tools#basic-tool-definition)
- but that's for a tool that's a static, top-level function known at import
time. Every tool here is a closure over one run's `store` (and, for the
retrieval tools, that run's `pipeline_config` shortlist-size defaults) -
built fresh inside `build_tools()` for each pipeline run, not defined once at
module load. `StructuredTool.from_function(func=fn, name=name)`
(https://reference.langchain.com/python/langchain-core/tools/structured/StructuredTool/from_function)
is the documented mechanism for exactly this: wrapping an already-existing
callable (here, a closure) into a `BaseTool` LangChain can bind to a model,
inferring the argument schema from the function's type hints and the tool's
description from its docstring - the same schema/description inference
`@tool` does, just applied to a function built at call time instead of
decorator time.
"""
from __future__ import annotations

from langchain_core.tools import StructuredTool

from .workbook_store import InMemoryWorkbookStore


def build_tools(store: InMemoryWorkbookStore) -> list[StructuredTool]:
    cfg = store.pipeline_config

    def get_feature_info(feature_id: str) -> dict:
        """Look up a feature's name and function group from the Index sheet."""
        return store.get_feature_info(feature_id) or {}

    def get_glossary_text() -> str:
        """Return the full Master List Abbreviations glossary as 'ABBR: definition' lines."""
        return store.get_glossary_text()

    def get_requirement_rows() -> list[dict]:
        """Return every raw row of the target requirement sheet (Requirement ID,
        Requirement Description, Category, Variant, Priority, Verification
        Method/Criteria/Stage, Source, Status, Release, Downstream
        Traceability, Remarks) - unfiltered, exactly as written in the sheet."""
        return store.get_requirement_rows()

    def get_feature_marked_rows(sheet: str, feature_id: str) -> list[dict]:
        """Return every row of a master sheet ('comm_matrix', 'app_param', or
        'io_signal') for the given feature id, each annotated with `_marker`
        (True/False if a clean O/x marker was found, null if the marker cell
        needs your judgment because it isn't a clean O or x) and `_marker_raw`
        (the literal cell content)."""
        return store.get_feature_marked_rows(sheet, feature_id)

    def lookup_command_name(signal_name: str, top_k: int = cfg.command_lookup_top_k) -> list[dict]:
        """Find the Command List entries whose Signal Name best matches
        `signal_name`, returning candidate Command name(s) with a match score."""
        return store.lookup_command_name(signal_name, top_k=top_k)

    def get_tolerance(name: str) -> dict:
        """Fuzzy-look-up a Tolerances sheet entry (e.g. 'Config_Tol_Spd') and
        return its description/unit/value. Empty dict if nothing matches."""
        entry = store.get_tolerance(name)
        return entry.model_dump() if entry else {}

    def get_model_input_mapping(signal: str) -> list[dict]:
        """Return every Model_Input_Mapping row for the given Signal (fuzzy
        matched), each with Test Case Input / Model Input / Model Output to ECU."""
        return [m.model_dump() for m in store.get_model_input_mapping(signal)]

    def search_compound_commands(query: str, top_k: int = cfg.compound_command_shortlist_size) -> list[dict]:
        """Keyword-overlap shortlist of compound commands (from both the Set
        and Verify sheets) matching `query`, ranked by score. Use
        get_compound_command_detail for the full step list of a shortlisted name."""
        return store.search_compound_commands(query, top_k=top_k)

    def get_compound_command_detail(name: str) -> dict:
        """Return the full ordered step list of one compound command by name
        (fuzzy matched). Empty dict if not found."""
        cmd = store.get_compound_command(name)
        return cmd.model_dump() if cmd else {}

    def search_library_functions(query: str, top_k: int = cfg.library_shortlist_size) -> list[dict]:
        """Keyword-overlap shortlist of Library List entries (Lib_* function
        signatures + descriptions) matching `query`, ranked by score."""
        return store.search_library(query, top_k=top_k)

    specs = [
        (get_feature_info, "get_feature_info"),
        (get_glossary_text, "get_glossary_text"),
        (get_requirement_rows, "get_requirement_rows"),
        (get_feature_marked_rows, "get_feature_marked_rows"),
        (lookup_command_name, "lookup_command_name"),
        (get_tolerance, "get_tolerance"),
        (get_model_input_mapping, "get_model_input_mapping"),
        (search_compound_commands, "search_compound_commands"),
        (get_compound_command_detail, "get_compound_command_detail"),
        (search_library_functions, "search_library_functions"),
    ]
    return [StructuredTool.from_function(func=fn, name=name) for fn, name in specs]
