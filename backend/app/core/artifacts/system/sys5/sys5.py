"""Entry point for the SYS5 artifact: agentic System Qualification Test Case
generation from a System Requirements workbook plus supporting reference
workbooks (Command List, Configuration/Tolerances, Compound Commands,
Keyword/Library descriptions), for one feature (config["req_sheet_name"]) at
a time.
"""
from __future__ import annotations

import os
import sys
import time
import zipfile
from datetime import datetime

if __package__ in (None, ""):
    # Running as a standalone script (`python sys5.py ...`), not imported as
    # part of the app.core.artifacts.system.sys5 package - there's no package
    # context for the relative imports below to resolve against. Locate
    # backend/ (this file's 5th ancestor: sys5/ -> system/ -> artifacts/ ->
    # core/ -> app/ -> backend/), put it on sys.path, and set __package__
    # (PEP 366) so the relative imports work exactly as they do when the
    # package is imported normally - no other module needs to change.
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), *([os.pardir] * 5))))
    __package__ = "app.core.artifacts.system.sys5"

from .config import Settings
from .graph import run_pipeline
from .logging_utils import configure_logging, get_logger
from .pipeline_config import PipelineConfig
from .schema import ProducedManifest


def generate(config: dict) -> str:
    settings = Settings.from_config(config)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    settings.timestamp = timestamp  # stashed for _finalise, since the frozen block below doesn't pass it through
    os.makedirs(settings.output_dir, exist_ok=True)  # required before the frozen block's os.listdir()

    pipeline_config = PipelineConfig.load()
    configure_logging(pipeline_config, output_dir=settings.output_dir)
    logger = get_logger(__name__)
    logger.info(
        "SYS5 generate() starting: project=%s feature=%s output_dir=%s",
        settings.project_name, settings.req_sheet_name, settings.output_dir,
    )
    started = time.monotonic()

    final_state = run_pipeline(settings, pipeline_config)
    produced: ProducedManifest = final_state["manifest"]
    produced.started_at = timestamp
    produced.finished_at = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("SYS5 generate() pipeline finished in %.1fs, writing zip archive", time.monotonic() - started)

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
    summary = (
        f"SYS5 generation complete for feature {produced.feature_id} ({produced.feature_name}): "
        f"{produced.requirement_count} requirement(s) -> {produced.test_case_count} test case(s) "
        f"({produced.flagged_count} flagged for review). Output: {zip_path}"
    )
    get_logger(__name__).info(summary)
    print(summary)
    return zip_path


def main() -> int:
    """Minimal standalone entry point: `python sys5.py <config.json>`. Reads
    the config dict from the given JSON file, runs generate(), and prints the
    resulting artifact path."""
    import json

    if len(sys.argv) < 2:
        print("Usage: python sys5.py <config.json>", file=sys.stderr)
        return 1

    with open(sys.argv[1]) as fh:
        config = json.load(fh)

    print(generate(config))
    return 0


if __name__ == "__main__":
    sys.exit(main())
