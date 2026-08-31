"""Central logging setup for a SYS5 run.

Every module gets its logger via `get_logger(__name__)`, and `stage_timer()`
standardizes the "stage started / stage finished in Xs" log lines used
throughout the pipeline (each outer-graph stage, each requirement, each
test-pattern row, each LLM call) so a run's progress and timing are visible
without instrumenting every call site by hand.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Iterator

from .pipeline_config import PipelineConfig

_ROOT_LOGGER_NAME = "sys5"


def configure_logging(pipeline_config: PipelineConfig, output_dir: str | None = None) -> logging.Logger:
    """Configure the `sys5` logger tree: console output always, plus a
    per-run log file inside `output_dir` (so it ships alongside the
    generated workbook/zip for later debugging) when
    `pipeline_config.log_to_file` is set. Safe to call more than once (e.g.
    once from sys5.py before the pipeline runs) - handlers are replaced, not
    stacked."""
    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(pipeline_config.log_level)
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(pipeline_config.log_format)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if pipeline_config.log_to_file and output_dir:
        os.makedirs(output_dir, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(output_dir, pipeline_config.log_file_name))
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    unknown = getattr(pipeline_config, "_unknown_keys", None)
    if unknown:
        root.warning("pipeline_config.json has unrecognized key(s), ignored: %s", sorted(unknown))

    return root


def get_logger(name: str) -> logging.Logger:
    if not (name == _ROOT_LOGGER_NAME or name.startswith(_ROOT_LOGGER_NAME + ".")):
        name = f"{_ROOT_LOGGER_NAME}.{name}"
    return logging.getLogger(name)


@contextmanager
def stage_timer(logger: logging.Logger, stage: str, **context) -> Iterator[None]:
    """Logs `-> stage (ctx...)` on entry and `<- stage done in Xs` on a clean
    exit, or `x  stage FAILED after Xs` (with traceback) if the block raises."""
    ctx = " ".join(f"{k}={v!r}" for k, v in context.items() if v is not None)
    suffix = f" ({ctx})" if ctx else ""
    logger.info("-> %s%s", stage, suffix)
    start = time.monotonic()
    try:
        yield
    except Exception:
        logger.exception("x  %s FAILED after %.1fs%s", stage, time.monotonic() - start, suffix)
        raise
    else:
        logger.info("<- %s done in %.1fs%s", stage, time.monotonic() - start, suffix)
