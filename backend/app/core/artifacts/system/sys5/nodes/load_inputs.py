"""Plain-Python step: locate and parse the System Requirements workbook into
an InMemoryWorkbookStore. Run once, before the graph is built (the store is
injected into every other node's closure - see graph.py) rather than as a
compiled graph node itself, since every other node's tools need the store to
already exist."""
from __future__ import annotations

from ..config import Settings
from ..logging_utils import get_logger, stage_timer
from ..pipeline_config import PipelineConfig
from ..workbook_store import InMemoryWorkbookStore, resolve_requirements_file

_logger = get_logger(__name__)


def load_inputs(settings: Settings, pipeline_config: PipelineConfig) -> InMemoryWorkbookStore:
    with stage_timer(_logger, "resolve_requirements_file", input_folder_path=settings.input_folder_path):
        file_path = resolve_requirements_file(settings.input_folder_path, settings.req_filename, settings.uploaded_files)
    _logger.info("requirements workbook resolved: %s", file_path)
    return InMemoryWorkbookStore.load(file_path, settings.req_sheet_name, pipeline_config)
