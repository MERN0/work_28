"""Builds the single `ChatOpenAI` client every agent/tool call in the SYS5
pipeline shares (one instance per `generate()` run - see graph.py's
`run_pipeline`, which builds it once and passes it into every node closure).

Every connection/retry parameter (model, credentials, temperature, retries,
timeout) is read from `PipelineConfig` (pipeline_config.py /
pipeline_config.json) rather than hardcoded here - see that module's
docstring for the full override chain (JSON file, then env vars).

## Why `ChatOpenAI` and not a provider-specific class

The SYS5 LLM endpoint (`pipeline_config.llm_api_base`) is an internal proxy
that speaks the OpenAI Chat Completions API, so `langchain_openai.ChatOpenAI`
is the correct client regardless of which underlying model the proxy actually
routes to - LangChain's docs are explicit that `ChatOpenAI` targets the
official OpenAI API surface and should be pointed at any endpoint that
implements it (self-hosted proxies included), whereas a provider-specific
package (e.g. `ChatDeepSeek`) is only needed when talking to that provider's
own non-standard API directly.
Reference: https://reference.langchain.com/python/langchain-openai/langchain_openai/chat_models/base/ChatOpenAI

## Parameter names

`ChatOpenAI`'s current documented constructor parameters are `api_key`,
`base_url`, and `timeout` (the same reference page above). Older examples
you may find online use `openai_api_key` / `openai_api_base` /
`request_timeout` - those still work today via Pydantic aliases for
backwards compatibility, but this module deliberately uses the current
canonical names so the code matches what the docs actually show.

## `output_version="v0"` / `use_responses_api=False` - message-format compatibility

Verified directly against the installed `langchain_openai` package source
(`chat_models/base.py`, `output_version` field docstring): as of
`langchain-openai>=1.0`, `ChatOpenAI`'s default `AIMessage` output format
changed from a plain string (`'v0'`, the pre-1.0 behavior) to `'responses/v1'`
- a list of typed content blocks. That default is meant for *real* OpenAI
endpoints (Responses API / current Chat Completions), not necessarily for
every OpenAI-compatible self-hosted backend.

`pipeline_config.llm_api_base` here is an internal litellm proxy in front of
a self-hosted, non-OpenAI model (`gpt-oss-120b` via vLLM) - and a real run
against it failed partway through a multi-turn tool-calling agent call with:

    litellm.BadRequestError: ... 1 validation error for Message
    content.0
      Input should be a valid dictionary or instance of Content [...]

i.e. litellm/vLLM rejected a follow-up request once the conversation history
included a prior tool call - a known LangChain/vLLM/gpt-oss compatibility
gap (see https://github.com/langchain-ai/langchain/issues/34751, filed
against this exact model family). `output_version="v0"` is the officially
documented value for exactly this situation (keep the older, simpler,
longer-battle-tested plain-string message format instead of content
blocks); `use_responses_api=False` is set unconditionally (not a config
knob) since this proxy only speaks Chat Completions and there is never a
reason to let LangChain's own auto-detection consider the Responses API for
it. `pipeline_config.llm_output_version` (default `"v0"`) exists so this can
still be overridden without a code change if a future endpoint needs it.
"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from .pipeline_config import PipelineConfig


def get_llm(pipeline_config: PipelineConfig, model: str | None = None) -> ChatOpenAI:
    """Construct a `ChatOpenAI` client configured from `pipeline_config`.

    Args:
        pipeline_config: The loaded `PipelineConfig` for this run (see
            `PipelineConfig.load()`). Supplies the model name, API
            key/base URL, temperature, retry/timeout settings, and
            `llm_output_version` (see module docstring).
        model: Optional override for `pipeline_config.llm_model` - used by
            `graph.run_pipeline()` to honor a per-run `config["model"]` value
            from the harness's `config` dict (see `config.Settings`) without
            that override having to live in `pipeline_config.json` itself.

    Returns:
        A `ChatOpenAI` instance. Nothing about it is SYS5-specific - it is
        a plain LangChain chat model that `agents.py` wraps with tool-calling
        and structured-output behavior.
    """
    optional: dict = {}
    if pipeline_config.llm_reasoning_effort:
        # Only sent when explicitly configured - see pipeline_config.py. A
        # reasoning model (this deployment's gpt-oss-120b) can spend far more
        # time on analysis tokens than on the small answers these stages ask
        # for; "low" is the lever for that, but it changes planning depth, so
        # it is never applied silently.
        optional["reasoning_effort"] = pipeline_config.llm_reasoning_effort

    return ChatOpenAI(
        model=model or pipeline_config.llm_model,
        api_key=pipeline_config.llm_api_key,
        base_url=pipeline_config.llm_api_base,
        temperature=pipeline_config.llm_temperature,
        max_retries=pipeline_config.llm_max_retries,
        timeout=pipeline_config.llm_timeout_seconds,
        output_version=pipeline_config.llm_output_version,
        use_responses_api=False,
        **optional,
    )
