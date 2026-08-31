"""LLM client factory. All defaults/overrides come from PipelineConfig (see
pipeline_config.py / pipeline_config.json) - the single place to change the
model, credentials, or retry/timeout behavior."""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from .pipeline_config import PipelineConfig


def get_llm(pipeline_config: PipelineConfig, model: str | None = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or pipeline_config.llm_model,
        openai_api_key=pipeline_config.llm_api_key,
        openai_api_base=pipeline_config.llm_api_base,
        temperature=pipeline_config.llm_temperature,
        max_retries=pipeline_config.llm_max_retries,
        request_timeout=pipeline_config.llm_timeout_seconds,
    )
