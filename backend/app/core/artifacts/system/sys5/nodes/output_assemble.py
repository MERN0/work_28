"""Plain-Python node: write the 5 output sheets from validated state and
produce the run's ProducedManifest."""
from __future__ import annotations

from .. import xlsx_writer
from ..config import Settings
from ..logging_utils import get_logger, stage_timer
from ..schema import ProducedManifest
from ..state import PipelineState

_logger = get_logger(__name__)


def build(settings: Settings):
    def node(state: PipelineState) -> PipelineState:
        with stage_timer(_logger, "output_assemble"):
            output_files = xlsx_writer.write_output_workbook(state, settings)
            flagged = sum(1 for tc in state.get("test_cases", []) if tc.status == "flagged")
            manifest = ProducedManifest(
                output_files=output_files,
                feature_id=state.get("feature_id", ""),
                feature_name=state.get("feature_name", ""),
                requirement_count=len(state.get("requirements", [])),
                test_case_count=len(state.get("test_cases", [])),
                flagged_count=flagged,
            )
            _logger.info(
                "output_assemble: wrote %s, %d test case(s) (%d flagged)",
                output_files, manifest.test_case_count, flagged,
            )
        return {**state, "manifest": manifest}

    return node
