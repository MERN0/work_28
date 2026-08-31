"""Version-robust wrapper around whichever create-agent API the installed
langchain/langgraph release exposes (`langchain.agents.create_agent` on newer
"LangChain 1.0"-era releases, `langgraph.prebuilt.create_react_agent` on
older ones - we can't confirm the exact installed version without network
access, so every node goes through this one adapter instead of importing
either API directly), plus a tool-use-then-structure helper so every agent
node gets a typed pydantic result regardless of that API's native
structured-output support.

Performance note: when the installed API supports `response_format` natively
(confirmed for `langchain.agents.create_agent`, where the structured answer
is produced as part of the existing tool-calling loop's final turn), using it
avoids a second, separate LLM round trip per call - this is the single
biggest lever on wall-clock time in the whole pipeline, since every agent
node makes at least one of these calls per requirement/test case. Controlled
by `pipeline_config.use_native_structured_output` (default on); falls back to
the manual two-call path if the native path doesn't yield a usable result.
"""
from __future__ import annotations

import inspect
import time
from typing import Any, Optional, Type, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ValidationError

from .logging_utils import get_logger
from .pipeline_config import PipelineConfig

try:
    from langchain.agents import create_agent as _create_agent  # type: ignore

    AGENT_API = "langchain.agents.create_agent"
except ImportError:  # pragma: no cover - depends on installed package set
    from langgraph.prebuilt import create_react_agent as _create_agent  # type: ignore

    AGENT_API = "langgraph.prebuilt.create_react_agent"

T = TypeVar("T", bound=BaseModel)
_logger = get_logger(__name__)

_AGENT_PARAMS = inspect.signature(_create_agent).parameters
SUPPORTS_NATIVE_RESPONSE_FORMAT = "response_format" in _AGENT_PARAMS


def make_agent(llm: BaseChatModel, tools: list, system_prompt: str, response_format: Optional[Type[BaseModel]] = None):
    """Build a tool-using agent, absorbing the create_agent/create_react_agent
    signature difference. Returns a compiled graph invocable as
    `.invoke({"messages": [...]}) -> {"messages": [...], "structured_response": ...}`."""
    kwargs: dict[str, Any] = {}
    if "system_prompt" in _AGENT_PARAMS:
        kwargs["system_prompt"] = system_prompt
    elif "prompt" in _AGENT_PARAMS:
        kwargs["prompt"] = system_prompt
    elif "state_modifier" in _AGENT_PARAMS:
        kwargs["state_modifier"] = system_prompt
    if response_format is not None and SUPPORTS_NATIVE_RESPONSE_FORMAT:
        kwargs["response_format"] = response_format
    return _create_agent(llm, tools, **kwargs)


def _transcript_text(result: dict) -> str:
    parts = []
    for message in result.get("messages", []):
        if isinstance(message, AIMessage) and message.content:
            parts.append(message.content if isinstance(message.content, str) else str(message.content))
    return "\n".join(parts)


def _manual_structured_call(
    llm: BaseChatModel, system_prompt: str, transcript: str, output_schema: Type[T], max_retries: int
) -> T:
    structurer = llm.with_structured_output(output_schema)
    structuring_prompt = (
        f"{system_prompt}\n\nBased on the reasoning and tool results below, produce the final "
        f"structured answer. Use only information that actually appeared in the tool results above - "
        f"never invent a signal, command, compound command, library call, or value that wasn't returned "
        f"by a tool.\n\n--- REASONING TRANSCRIPT ---\n{transcript}\n--- END TRANSCRIPT ---"
    )
    last_error: Exception | None = None
    for _ in range(max_retries + 1):
        try:
            parsed = structurer.invoke(structuring_prompt)
            return parsed if isinstance(parsed, output_schema) else output_schema.model_validate(parsed)
        except (ValidationError, ValueError) as exc:
            last_error = exc
            structuring_prompt += f"\n\nYour previous answer was invalid: {exc}\nPlease correct it and answer again."
    raise RuntimeError(f"Failed to obtain a valid {output_schema.__name__} after {max_retries + 1} attempts") from last_error


def run_agent_with_structured_output(
    llm: BaseChatModel,
    tools: list,
    system_prompt: str,
    user_input: str,
    output_schema: Type[T],
    pipeline_config: Optional[PipelineConfig] = None,
) -> tuple[T, str]:
    """Run a tool-augmented agent and return a typed `output_schema` result.

    Uses the installed API's native `response_format` (one round trip) when
    available and enabled; otherwise, or if that doesn't yield a usable
    result, falls back to the version-robust two-call pattern (run the tool
    loop to completion, then one separate `with_structured_output` call).

    Returns (parsed_output, raw_transcript_text) - the transcript is kept for
    logging/debugging and for feeding into the validation/correction loop.
    """
    max_retries = pipeline_config.structured_output_max_retries if pipeline_config else 2
    use_native = SUPPORTS_NATIVE_RESPONSE_FORMAT and (pipeline_config is None or pipeline_config.use_native_structured_output)
    started = time.monotonic()

    if use_native:
        agent = make_agent(llm, tools, system_prompt, response_format=output_schema)
        result = agent.invoke({"messages": [HumanMessage(content=user_input)]})
        transcript = _transcript_text(result)
        structured = result.get("structured_response")
        if structured is not None:
            parsed = structured if isinstance(structured, output_schema) else output_schema.model_validate(structured)
            _logger.debug("agent call (native response_format) took %.1fs", time.monotonic() - started)
            return parsed, transcript
        _logger.warning("native response_format produced no structured_response; falling back to manual structuring call")

    agent = make_agent(llm, tools, system_prompt)
    result = agent.invoke({"messages": [HumanMessage(content=user_input)]})
    transcript = _transcript_text(result)
    parsed = _manual_structured_call(llm, system_prompt, transcript, output_schema, max_retries)
    _logger.debug("agent call (manual two-call structuring) took %.1fs", time.monotonic() - started)
    return parsed, transcript
