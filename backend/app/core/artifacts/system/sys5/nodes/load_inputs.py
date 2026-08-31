"""Plain-Python step: locate and parse all 5 input workbooks into an
InMemoryWorkbookStore. Run once, before the graph is built (the store is
injected into every other node's closure - see graph.py) rather than as a
compiled graph node itself, since every other node's tools need the store to
already exist."""
from __future__ import annotations

from ..config import Settings
from ..logging_utils import get_logger, stage_timer
from ..pipeline_config import PipelineConfig
from ..workbook_store import InMemoryWorkbookStore, resolve_input_files

_logger = get_logger(__name__)


def load_inputs(settings: Settings, pipeline_config: PipelineConfig) -> InMemoryWorkbookStore:
    with stage_timer(_logger, "resolve_input_files", input_folder_path=settings.input_folder_path):
        file_paths = resolve_input_files(settings.input_folder_path, settings.req_filename, settings.uploaded_files)
    for role, path in file_paths.items():
        _logger.info("input file resolved: %s -> %s", role, path)
    return InMemoryWorkbookStore.load(file_paths, settings.req_sheet_name, pipeline_config)
