"""One place for every tunable engineering knob in the SYS5 pipeline: LLM
connection/retry parameters, fuzzy-matching thresholds, retrieval shortlist
sizes, concurrency, and logging. Everything here has a sensible default (the
values already in use before this file existed) but can be overridden by
editing `pipeline_config.json` directly - no code change needed.

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
    # `ChatOpenAI`'s own HTTP-level retry already retries a slow/failed call
    # up to llm_max_retries times, each bounded by this timeout - so a call
    # that *always* times out (not flaky, just genuinely slow) needs a
    # longer timeout, not more retries. 120s proved too short for
    # test_pattern_gen against the real gpt-oss-120b proxy (a reasoning
    # model, first stage to ask for a nontrivial synthesized answer rather
    # than a classification) - raised to 300s. Override per-run without a
    # code change via the SYS5_LLM_TIMEOUT env var if 300s still isn't enough.
    llm_timeout_seconds: int = 300
    # Retries for a structured-output call whose answer fails pydantic
    # validation - see agents.py. Separate from llm_max_retries (HTTP-level).
    structured_output_max_retries: int = 2
    # How `llm.with_structured_output()` asks for a typed answer:
    # - "json_schema" (langchain-openai's default for ChatOpenAI): sends the
    #   schema as a strict `response_format`. A self-hosted backend (vLLM)
    #   compiles it into a grammar for guided decoding - fast for a closed
    #   schema, pathological for one with open-ended `additionalProperties`
    #   maps (see nodes/test_pattern_gen.py's docstring; every schema in this
    #   pipeline is deliberately kept closed for this reason).
    # - "function_calling": the older approach - binds one synthetic tool and
    #   forces tool_choice. Switch to this if a particular backend build
    #   handles json_schema poorly.
    structured_output_method: str = "json_schema"
    # gpt-oss (and other reasoning models) can accept an OpenAI
    # `reasoning_effort` param ("low"/"medium"/"high") to trade planning depth
    # for wall-clock time. Defaults to None (not sent) - tried as "low" for
    # exactly that wall-clock reason, but a real run against this deployment's
    # litellm proxy came back with a hard 400: `litellm.UnsupportedParamsError:
    # openai does not support parameters: ['reasoning_effort'] ... To drop
    # these, set litellm.drop_params=True`. This proxy/model routing does not
    # accept the param at all (not a soft ignore), so sending it by default
    # breaks every stage, not just the reasoning-heavy ones. Only re-enable
    # (set to "low"/"medium"/"high") once the proxy's own
    # `litellm_settings.drop_params: true` (or `allowed_openai_params:
    # ['reasoning_effort']`) is confirmed - a client-side setting can't work
    # around a server that flatly rejects the parameter.
    llm_reasoning_effort: str | None = None
    # `ChatOpenAI(output_version=...)` - "v0" keeps AIMessage.content a plain
    # string (langchain-openai's pre-1.0 format) instead of the >=1.0 default
    # ("responses/v1"), a list of typed content blocks. The SYS5 endpoint is
    # an internal litellm proxy in front of a self-hosted, non-OpenAI model
    # (gpt-oss-120b via vLLM), not real OpenAI - it does not reliably round-
    # trip the newer block format through a multi-turn tool-calling
    # conversation (confirmed against a real run: litellm rejected a
    # follow-up request with a "Message content.0 ... ValidatorIterator"
    # pydantic error once prior turns included tool calls - a known
    # LangChain/vLLM/gpt-oss compatibility gap, see
    # https://github.com/langchain-ai/langchain/issues/34751). "v0" is the
    # official, documented backwards-compatibility value for exactly this -
    # see llm.py's docstring. See get_llm() for `use_responses_api=False`,
    # set unconditionally alongside this rather than as a config knob, since
    # this proxy is Chat-Completions-only and there is never a reason to
    # let LangChain's auto-detection consider the Responses API for it.
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
    command_match_threshold: int = 80         # Comm Matrix Signal name -> Command List Command name
    model_input_match_threshold: int = 70     # factor value -> Model_Input_Mapping Test Case Input
    hallucination_match_threshold: int = 92   # the anti-hallucination guardrail (store.exists) - deliberately strict
    general_fuzzy_threshold: int = 90         # default for excel_io.fuzzy_equal/fuzzy_find when no other threshold applies

    # -- Deterministic compound-command / library selection -------------------
    # compound_command_map.py selects directly from the keyword-overlap
    # search results (rapidfuzz token_set_ratio of the requirement text
    # against each candidate's name/steps or signature/description) - no LLM
    # judgment call, so these two knobs are the only levers on what gets
    # selected. The *_select_threshold values are deliberately lower than the
    # name-matching thresholds above (75-95): they score a whole requirement
    # paragraph's vocabulary against a command's name+steps text, which is a
    # much looser comparison than matching one short string to another. Start
    # here and tune against real run logs (`compound_command_map: req=...`
    # lines) if too many irrelevant commands get selected (raise the
    # threshold) or too few real ones do (lower it, or raise the *_max_selected
    # cap).
    compound_command_max_selected: int = 5
    library_max_selected: int = 5
    compound_command_select_threshold: int = 45
    library_select_threshold: int = 45
    command_lookup_top_k: int = 3

    # -- Performance / concurrency --------------------------------------------
    # User-directed hard cap: at most this many test cases per requirement,
    # regardless of how large the fixed-factor combinatorial sweep is -
    # test_pattern_gen.py applies this after expansion (round-robin across
    # scenarios first, so a cap below the scenario count doesn't starve every
    # scenario but the first - see its _cap_rows docstring). The single
    # biggest lever on a requirement's total LLM calls (each row costs at
    # least one generate + one validate call, more if corrected), so this is
    # also the most direct fix for "one requirement takes forever" - keep the
    # factor tables in factors.py scoped to what actually needs coverage
    # (see its own comments) rather than relying on this cap to hide an
    # unnecessarily large sweep.
    max_test_cases_per_requirement: int = 5
    # How many test-pattern rows to generate+validate concurrently in
    # test_case_loop.py. Each row is an independent unit of work (its own
    # TestCaseState, its own LLM calls), so raising this is structurally
    # safe - but user-reported output against the real deployment (self-
    # hosted gpt-oss-120b via vLLM/litellm) showed real quality degradation
    # under concurrent load: later test cases in a run came back with
    # thinner/incomplete steps than the first. Defaults to 1 (fully
    # sequential, one test-pattern row at a time) until that backend-under-
    # load behavior is understood well enough to trust a higher value again;
    # raise it back only against a deployment/model confirmed not to degrade
    # under concurrent requests.
    max_concurrent_test_cases: int = 1
    # Run validate_pass1 and validate_pass2 as ONE combined LLM call (two
    # rubrics, one round trip) instead of two separate calls. Roughly halves
    # the validation stage's LLM round trips with no loss of rubric coverage.
    # Set false to restore the original two-separate-calls behavior.
    combine_validation_passes: bool = True

    # -- Output ----------------------------------------------------------------
    test_case_id_prefix: str = "TMHC_SQTC"

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
