"""Entry point for the SYS5 artifact: extracts every valid Test Pattern for
every available Functional Requirement of one feature
(config["req_sheet_name"]) from a System Requirements workbook, and saves the
result as a single JSON file.
"""
from __future__ import annotations

import json
import os
import sys
import time
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
from .state import PipelineState


def _build_payload(state: PipelineState, generated_at: str) -> dict:
    test_patterns = state.get("test_patterns", {})
    return {
        "feature_id": state.get("feature_id", ""),
        "feature_name": state.get("feature_name", ""),
        "function_group": state.get("function_group", ""),
        "generated_at": generated_at,
        "requirements": [
            {
                **req.model_dump(),
                "test_patterns": [row.model_dump() for row in test_patterns.get(req.req_id, [])],
            }
            for req in state.get("requirements", [])
        ],
    }


def generate(config: dict) -> str:
    settings = Settings.from_config(config)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(settings.output_dir, exist_ok=True)  # required before the log file / JSON output are written

    pipeline_config = PipelineConfig.load()
    configure_logging(pipeline_config, output_dir=settings.output_dir)
    logger = get_logger(__name__)
    logger.info(
        "SYS5 generate() starting: project=%s feature=%s output_dir=%s",
        settings.project_name, settings.req_sheet_name, settings.output_dir,
    )
    started = time.monotonic()

    final_state = run_pipeline(settings, pipeline_config)
    payload = _build_payload(final_state, datetime.now().isoformat(timespec="seconds"))

    json_path = os.path.join(settings.output_dir, f"SYS5_TestPatterns_{settings.project_name}_{timestamp}.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    pattern_count = sum(len(p["test_patterns"]) for p in payload["requirements"])
    summary = (
        f"SYS5 test-pattern extraction complete for feature {payload['feature_id']} ({payload['feature_name']}): "
        f"{len(payload['requirements'])} requirement(s) -> {pattern_count} test pattern row(s) "
        f"in {time.monotonic() - started:.1f}s. Output: {json_path}"
    )
    logger.info(summary)
    print(summary)
    return json_path


def main() -> int:
    """Minimal standalone entry point: `python sys5.py <config.json>`. Reads
    the config dict from the given JSON file, runs generate(), and prints the
    resulting artifact path."""
    if len(sys.argv) < 2:
        print("Usage: python sys5.py <config.json>", file=sys.stderr)
        return 1

    with open(sys.argv[1]) as fh:
        config = json.load(fh)

    print(generate(config))
    return 0


if __name__ == "__main__":
    sys.exit(main())
