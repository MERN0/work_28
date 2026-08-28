"""Version-robust wrapper around whichever create-agent API the installed
langchain/langgraph release exposes (`langchain.agents.create_agent` on newer
"LangChain 1.0"-era releases, `langgraph.prebuilt.create_react_agent` on
older ones - we can't confirm the exact installed version without network
access, so every node goes through this one adapter instead of importing
either API directly), plus a tool-use-then-structure helper so every agent
node gets a typed pydantic result regardless of that API's native
structured-output support.
"""
from __future__ import annotations

import inspect
from typing import Any, Type, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ValidationError

try:
    from langchain.agents import create_agent as _create_agent  # type: ignore

    AGENT_API = "langchain.agents.create_agent"
except ImportError:  # pragma: no cover - depends on installed package set
    from langgraph.prebuilt import create_react_agent as _create_agent  # type: ignore

    AGENT_API = "langgraph.prebuilt.create_react_agent"

T = TypeVar("T", bound=BaseModel)

_AGENT_PARAMS = inspect.signature(_create_agent).parameters


def make_agent(llm: BaseChatModel, tools: list, system_prompt: str):
    """Build a tool-using agent, absorbing the create_agent/create_react_agent
    signature difference. Returns a compiled graph invocable as
    `.invoke({"messages": [...]}) -> {"messages": [...]}`."""
    kwargs: dict[str, Any] = {}
    if "system_prompt" in _AGENT_PARAMS:
        kwargs["system_prompt"] = system_prompt
    elif "prompt" in _AGENT_PARAMS:
        kwargs["prompt"] = system_prompt
    elif "state_modifier" in _AGENT_PARAMS:
        kwargs["state_modifier"] = system_prompt
    return _create_agent(llm, tools, **kwargs)


def _transcript_text(result: dict) -> str:
    parts = []
    for message in result.get("messages", []):
        if isinstance(message, AIMessage) and message.content:
            parts.append(message.content if isinstance(message.content, str) else str(message.content))
    return "\n".join(parts)


def run_agent_with_structured_output(
    llm: BaseChatModel,
    tools: list,
    system_prompt: str,
    user_input: str,
    output_schema: Type[T],
    max_retries: int = 2,
) -> tuple[T, str]:
    """Run a tool-augmented agent to completion, then shape its final answer
    into `output_schema` via a separate `with_structured_output` call (the
    version-robust two-call pattern), rather than requiring the installed
    agent API to natively support tool use + structured output together.

    Returns (parsed_output, raw_transcript_text) - the transcript is kept for
    logging/debugging and for feeding into the validation/correction loop.
    """
    agent = make_agent(llm, tools, system_prompt)
    result = agent.invoke({"messages": [HumanMessage(content=user_input)]})
    transcript = _transcript_text(result)

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
            if isinstance(parsed, output_schema):
                return parsed, transcript
            return output_schema.model_validate(parsed), transcript
        except (ValidationError, ValueError) as exc:
            last_error = exc
            structuring_prompt += f"\n\nYour previous answer was invalid: {exc}\nPlease correct it and answer again."
    raise RuntimeError(f"Failed to obtain a valid {output_schema.__name__} after {max_retries + 1} attempts") from last_error
