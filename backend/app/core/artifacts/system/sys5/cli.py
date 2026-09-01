"""Command-line runner for a real SYS5 test-pattern extraction run - a
convenience wrapper around the exact same `sys5.generate(config)` entry point
the production harness calls, so a manual CLI run and a real harness run
exercise identical code.

This makes real calls to whatever LLM endpoint `pipeline_config.json` (or its
env var overrides) currently points at, so it needs real network access to
that endpoint.

## Usage

    python cli.py \\
        --requirements "/path/to/System Requirements.xlsx" \\
        --feature-id 019 \\
        --output-dir /path/to/output

...or, if the workbook lives in a folder by itself, point --input-dir at it
instead and skip --requirements.

`--feature-id` is the System Requirements workbook's sheet name for the
feature to extract test patterns for (the `req_sheet_name` the rest of the
pipeline calls it) - e.g. '019' for Slope Assist. It must already have a
factor table registered in factors.py, or the run fails fast with
MissingFactorTableError before any LLM work starts.

Runs standalone (`python cli.py ...`) or as part of the package
(`python -m app.core.artifacts.system.sys5.cli ...`) via the same PEP 366
dual-mode import pattern as sys5.py - see that file's module docstring.
"""
from __future__ import annotations

import argparse
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), *([os.pardir] * 5))))
    __package__ = "app.core.artifacts.system.sys5"

from .sys5 import generate


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract all valid Test Pattern rows for every Functional Requirement of one feature, as JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input-dir", default="", help="Folder containing the System Requirements workbook.")
    p.add_argument("--requirements", default="", help="Path to the System Requirements workbook.")
    p.add_argument("--feature-id", required=True, help="Requirement-sheet name / feature id to extract test patterns for (e.g. '019').")
    p.add_argument("--output-dir", required=True, help="Directory to write the output JSON into.")
    p.add_argument("--project-name", default="SYS5_CLI_Run", help="Used in the output JSON's filename. Default: SYS5_CLI_Run.")
    p.add_argument("--model", default="", help="Optional LLM model override (default: pipeline_config.json's llm_model).")
    return p.parse_args(argv)


def build_config(args: argparse.Namespace) -> dict:
    """Translate CLI args into the same `config` dict shape `Settings.from_config`
    expects from the production harness. Validates the file path up front so a
    typo fails immediately with a clear message, rather than surfacing later
    as a confusing MissingInputFileError deep inside the pipeline."""
    uploaded = [args.requirements] if args.requirements else []
    for path in uploaded:
        if not os.path.isfile(path):
            raise SystemExit(f"Input file not found: {path}")
    if not uploaded and not args.input_dir:
        raise SystemExit("Provide either --input-dir or --requirements.")
    if args.input_dir and not os.path.isdir(args.input_dir):
        raise SystemExit(f"--input-dir not found: {args.input_dir}")

    return {
        "project_name": args.project_name,
        "artifact": "SYS5",
        "model": args.model,
        "input_folder_path": args.input_dir,
        "output_folder_path": args.output_dir,
        "output_dir": args.output_dir,
        "uploaded_files": uploaded,
        "req_filename": os.path.basename(args.requirements) if args.requirements else "",
        "req_sheet_name": args.feature_id,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    os.makedirs(args.output_dir, exist_ok=True)
    config = build_config(args)
    result_path = generate(config)
    print(result_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
