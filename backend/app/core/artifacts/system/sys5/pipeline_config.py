"""One place for every tunable engineering knob in the SYS5 pipeline: LLM
connection/retry parameters, fuzzy-matching thresholds, and logging.
Everything here has a sensible default (the values already in use before
this file existed) but can be overridden by editing `pipeline_config.json`
directly - no code change needed.

Load order (later wins): dataclass defaults -> pipeline_config.json (path
from `SYS5_PIPELINE_CONFIG_PATH` env var, else the file next to this module)
-> a small set of env vars for the LLM connection specifically (kept as env
overrides, not committed to the JSON file, since they're commonly
secrets/deployment-specific: SYS5_LLM_MODEL, SYS5_LLM_API_KEY,
SYS5_LLM_API_BASE, SYS5_LLM_MAX_RETRIES, SYS5_LLM_TIMEOUT).
"""
from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, fields

_DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "pipeline_config.json")


@dataclass
class PipelineConfig:
    # -- LLM connection & call resilience -----------------------------------
    llm_model: str = "llm-1-gpt-osx-120b"
    llm_api_key: str = "sk-dfK6wRAt7vIiphRybrrdJQ"
    llm_api_base: str = "http://10.1.2.186:4000"
    llm_temperature: float = 0
    llm_max_retries: int = 3
    llm_timeout_seconds: int = 300
    # Retries for a structured-output call whose answer fails pydantic
    # validation - see agents.py. Separate from llm_max_retries (HTTP-level).
    structured_output_max_retries: int = 2
    # How `llm.with_structured_output()` asks for a typed answer:
    # - "json_schema" (langchain-openai's default for ChatOpenAI): sends the
    #   schema as a strict `response_format`. A self-hosted backend (vLLM)
    #   compiles it into a grammar for guided decoding - fast for a closed
    #   schema, pathological for one with open-ended `additionalProperties`
    #   maps (see nodes/test_pattern_gen.py's docstring; the schema stays
    #   closed for this reason).
    # - "function_calling": the older approach - binds one synthetic tool and
    #   forces tool_choice. Switch to this if a particular backend build
    #   handles json_schema poorly.
    structured_output_method: str = "json_schema"
    # gpt-oss (and other reasoning models) can accept an OpenAI
    # `reasoning_effort` param ("low"/"medium"/"high") to trade planning depth
    # for wall-clock time. Defaults to None (not sent) - this deployment's
    # litellm proxy hard-rejects the param (`UnsupportedParamsError`) unless
    # `litellm_settings.drop_params: true` is set server-side; only re-enable
    # once that's confirmed.
    llm_reasoning_effort: str | None = None
    # `ChatOpenAI(output_version=...)` - "v0" keeps AIMessage.content a plain
    # string (langchain-openai's pre-1.0 format) instead of the >=1.0 default
    # ("responses/v1"), a list of typed content blocks. The SYS5 endpoint is
    # an internal litellm proxy in front of a self-hosted, non-OpenAI model
    # (gpt-oss-120b via vLLM), not real OpenAI - "v0" is the documented
    # backwards-compatibility value for exactly that. See llm.py's docstring.
    llm_output_version: str = "v0"

    # -- Fuzzy-matching thresholds (0-100, higher = stricter) ---------------
    header_row_match_threshold: int = 75      # locating a sheet's header row among title/banner rows
    column_match_threshold: int = 75          # matching a real column header to a canonical field name
    sheet_name_match_threshold: int = 80      # matching a workbook's sheet name to an expected name
    # Requirement sheet Category value classification (fully deterministic -
    # a row that doesn't cross this threshold against the known vocabulary is
    # dropped, never guessed). Deliberately much stricter than the other
    # 75-80 header/column thresholds above: 'Functional Requirement' vs
    # 'NonFunctional Requirement' (space- or underscore-separated, e.g. 'Non
    # Functional Requirement') scores ~91.7 on token_sort_ratio - a naive 85
    # threshold let a non-functional row silently fast-path as a testable
    # Functional Requirement. 95 sits above that collision while still
    # matching genuine typos ('Functional Requirment' etc, 97.7+).
    category_match_threshold: int = 95

    # -- Performance --------------------------------------------------------
    # User-directed hard cap: at most this many test-pattern rows per
    # requirement, regardless of how large the fixed-factor combinatorial
    # sweep is - test_pattern_gen.py applies this after expansion
    # (round-robin across scenarios first, so a cap below the scenario count
    # doesn't starve every scenario but the first - see its _cap_rows
    # docstring).
    max_test_cases_per_requirement: int = 5

    # -- Logging -----------------------------------------------------------
    log_level: str = "INFO"
    log_to_file: bool = True
    log_file_name: str = "sys5_run.log"
    log_format: str = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

    @classmethod
    def load(cls, path: str | None = None) -> "PipelineConfig":
        path = path or os.environ.get("SYS5_PIPELINE_CONFIG_PATH", _DEFAULT_CONFIG_PATH)
        data: dict = {}
        if path and os.path.isfile(path):
            with open(path) as fh:
                data = json.load(fh)

        valid_fields = {f.name for f in fields(cls)}
        unknown = set(data) - valid_fields
        kwargs = {k: v for k, v in data.items() if k in valid_fields}
        config = cls(**kwargs)
        if unknown:
            # Surfaced via logging (configured after this loads) as a warning
            # by the caller, not raised - an unrecognized key in a hand-edited
            # settings file shouldn't stop a run.
            config._unknown_keys = unknown  # type: ignore[attr-defined]

        env_overrides = {
            "llm_model": os.environ.get("SYS5_LLM_MODEL"),
            "llm_api_key": os.environ.get("SYS5_LLM_API_KEY"),
            "llm_api_base": os.environ.get("SYS5_LLM_API_BASE"),
        }
        for key, value in env_overrides.items():
            if value:
                setattr(config, key, value)
        if os.environ.get("SYS5_LLM_MAX_RETRIES"):
            config.llm_max_retries = int(os.environ["SYS5_LLM_MAX_RETRIES"])
        if os.environ.get("SYS5_LLM_TIMEOUT"):
            config.llm_timeout_seconds = int(os.environ["SYS5_LLM_TIMEOUT"])

        return config

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)
