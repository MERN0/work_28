"""Plain-Python step: locate and parse all 5 input workbooks into an
InMemoryWorkbookStore. Run once, before the graph is built (the store is
injected into every other node's closure - see graph.py) rather than as a
compiled graph node itself, since every other node's tools need the store to
already exist."""
from __future__ import annotations

from ..config import Settings
from ..workbook_store import InMemoryWorkbookStore, resolve_input_files


def load_inputs(settings: Settings) -> InMemoryWorkbookStore:
    file_paths = resolve_input_files(settings.input_folder_path, settings.req_filename, settings.uploaded_files)
    return InMemoryWorkbookStore.load(file_paths, settings.req_sheet_name)
