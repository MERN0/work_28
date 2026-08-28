"""Entry point for the SYS5 artifact: agentic System Qualification Test Case
generation from a System Requirements workbook plus supporting reference
workbooks (Command List, Configuration/Tolerances, Compound Commands,
Keyword/Library descriptions), for one feature (config["req_sheet_name"]) at
a time.
"""
from __future__ import annotations

import os
import zipfile
from datetime import datetime

from .config import Settings
from .graph import run_pipeline
from .schema import ProducedManifest


def generate(config: dict) -> str:
    settings = Settings.from_config(config)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    settings.timestamp = timestamp  # stashed for _finalise, since the frozen block below doesn't pass it through
    os.makedirs(settings.output_dir, exist_ok=True)  # required before the frozen block's os.listdir()

    final_state = run_pipeline(settings)
    produced: ProducedManifest = final_state["manifest"]
    produced.started_at = timestamp
    produced.finished_at = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ========================== Donot change ==========================
    zip_path = os.path.join(settings.output_dir, f"SYS5_{settings.project_name}_{timestamp}.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename in os.listdir(settings.output_dir):
            file_path = os.path.join(settings.output_dir, filename)
            if os.path.isfile(file_path) and not filename.endswith(".zip"):
                zf.write(file_path, arcname=filename)
    return str(_finalise(produced, settings))


def _finalise(produced: ProducedManifest, settings: Settings) -> str:
    """Runs after the zip is already written, so anything written here would
    not ship inside it - this only summarizes and returns the run's result
    path. Recomputes the zip path from `settings` rather than needing it
    passed in, since the frozen block above only receives (produced, settings)."""
    zip_path = os.path.join(settings.output_dir, f"SYS5_{settings.project_name}_{settings.timestamp}.zip")
    print(
        f"SYS5 generation complete for feature {produced.feature_id} ({produced.feature_name}): "
        f"{produced.requirement_count} requirement(s) -> {produced.test_case_count} test case(s) "
        f"({produced.flagged_count} flagged for review). Output: {zip_path}"
    )
    return zip_path
