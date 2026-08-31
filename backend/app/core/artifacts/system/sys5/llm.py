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
"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from .pipeline_config import PipelineConfig


def get_llm(pipeline_config: PipelineConfig, model: str | None = None) -> ChatOpenAI:
    """Construct a `ChatOpenAI` client configured from `pipeline_config`.

    Args:
        pipeline_config: The loaded `PipelineConfig` for this run (see
            `PipelineConfig.load()`). Supplies the model name, API
            key/base URL, temperature, and retry/timeout settings.
        model: Optional override for `pipeline_config.llm_model` - used by
            `graph.run_pipeline()` to honor a per-run `config["model"]` value
            from the harness's `config` dict (see `config.Settings`) without
            that override having to live in `pipeline_config.json` itself.

    Returns:
        A `ChatOpenAI` instance. Nothing about it is SYS5-specific - it is
        a plain LangChain chat model that `agents.py` wraps with tool-calling
        and structured-output behavior.
    """
    return ChatOpenAI(
        model=model or pipeline_config.llm_model,
        api_key=pipeline_config.llm_api_key,
        base_url=pipeline_config.llm_api_base,
        temperature=pipeline_config.llm_temperature,
        max_retries=pipeline_config.llm_max_retries,
        timeout=pipeline_config.llm_timeout_seconds,
    )
