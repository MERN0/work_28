"""LLM client factory. Defaults match the example wiring given for this
artifact exactly, overridable via env vars so a deployment can point at a
different proxy/key without a code change."""
from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

_DEFAULT_MODEL = "llm-1-gpt-osx-120b"
_DEFAULT_API_KEY = "sk-dfK6wRAt7vIiphRybrrdJQ"
_DEFAULT_API_BASE = "http://10.1.2.186:4000"


def get_llm(model: str | None = None, temperature: float = 0) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or os.environ.get("SYS5_LLM_MODEL", _DEFAULT_MODEL),
        openai_api_key=os.environ.get("SYS5_LLM_API_KEY", _DEFAULT_API_KEY),
        openai_api_base=os.environ.get("SYS5_LLM_API_BASE", _DEFAULT_API_BASE),
        temperature=temperature,
        max_retries=int(os.environ.get("SYS5_LLM_MAX_RETRIES", "3")),
        request_timeout=int(os.environ.get("SYS5_LLM_TIMEOUT", "120")),
    )
