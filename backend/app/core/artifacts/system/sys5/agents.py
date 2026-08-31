"""Single choke point for "run an LLM agent that can call tools and must
return a typed pydantic object" - every agent-backed node in `nodes/*.py`
calls `run_agent_with_structured_output()` from this module instead of
touching `langchain`/`langgraph` agent APIs directly. Two problems are
solved here, once, instead of in every node:

1. **Which agent-construction API is installed.** `langgraph.prebuilt.create_react_agent`
   is now deprecated in favor of `langchain.agents.create_agent`
   (confirmed via `reference-langchain` docs lookup on this codebase's
   installed version: `create_react_agent`'s doc page carries an explicit
   deprecation warning pointing at `create_agent`, and the "Migrating from
   LangGraph v0" guide covers the same move -
   https://docs.langchain.com/oss/python/migrate/langgraph-v1). This
   repository's `requirements.txt` pins a `langchain>=1.0` release where
   `create_agent` exists (verified live: `AGENT_API` below prints
   `"langchain.agents.create_agent"` in this environment), but since we
   cannot guarantee every future install will have it, `make_agent()` tries
   `create_agent` first and only falls back to the deprecated
   `create_react_agent` if the import fails. Every node calls `make_agent()`
   (or, more commonly, `run_agent_with_structured_output()`) - never
   `create_agent`/`create_react_agent` directly - so this is the *only*
   place that needs to know which one is actually installed.

2. **Getting a typed answer out of a tool-using agent, in as few LLM round
   trips as possible.** See `run_agent_with_structured_output()`'s docstring
   for the two strategies and why the "native" one matters for wall-clock
   time.

## Background: how `response_format` works (from the docs)

Passing `response_format=SomeSchema` to `create_agent()` makes the compiled
graph's final state carry the parsed object under the `"structured_response"`
key - not folded into `"messages"`. LangChain auto-selects one of two
strategies per https://docs.langchain.com/oss/python/langchain/structured-output:

- `ProviderStrategy` - the model provider's own native structured-output/
  JSON-mode feature (e.g. OpenAI's `response_format` on the Chat Completions
  API itself). No extra LLM call: the agent's last turn *is* the structured
  answer.
- `ToolStrategy` - a synthetic "return_structured_output" tool the model is
  asked to call as its final action. Still typically resolves within the
  same tool-calling loop (the model's last tool call *is* the structured
  answer) rather than requiring a whole separate follow-up request.

Either way, going through `response_format` is meant to avoid the older
pattern of running an agent to completion and then making a *second*,
separate `llm.with_structured_output(...)` call against the transcript just
to shape the answer - which is exactly the "manual" fallback path in this
module, kept only for when the native path can't be used or doesn't produce
a result.

Reference pages consulted for this module (fetched via the `docs-langchain`
/ `reference-langchain` MCP tools, not assumed from memory):
- https://reference.langchain.com/python/langchain/agents/factory/create_agent
- https://reference.langchain.com/python/langgraph.prebuilt/chat_agent_executor/create_react_agent
- https://docs.langchain.com/oss/python/langchain/structured-output
- https://docs.langchain.com/oss/python/migrate/langchain-v1#tool-and-provider-strategies
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
    # Deprecated fallback - see module docstring point 1. Kept only so this
    # module still works on an older langgraph-only install; a fresh
    # `pip install -r requirements.txt` on this repo will never hit this branch.
    from langgraph.prebuilt import create_react_agent as _create_agent  # type: ignore

    AGENT_API = "langgraph.prebuilt.create_react_agent"

T = TypeVar("T", bound=BaseModel)
_logger = get_logger(__name__)

#: The parameter names `_create_agent` actually accepts, introspected once at
#: import time. Used below to build the right kwargs for whichever of the two
#: APIs got imported, without a second `if AGENT_API == ...` branch per call site.
_AGENT_PARAMS = inspect.signature(_create_agent).parameters

#: Whether the installed agent-construction function accepts `response_format`
#: at all - both `create_agent` and `create_react_agent` do today, but this is
#: computed rather than assumed so a future/older API without it still works
#: (falls straight through to the manual two-call path every time).
SUPPORTS_NATIVE_RESPONSE_FORMAT = "response_format" in _AGENT_PARAMS


def make_agent(
    llm: BaseChatModel, tools: list, system_prompt: str, response_format: Optional[Type[BaseModel]] = None
):
    """Build one tool-calling agent graph, hiding the `create_agent` vs.
    `create_react_agent` signature difference.

    `create_agent`'s system-prompt parameter is named `system_prompt`;
    `create_react_agent`'s is named `prompt` (with `state_modifier` as an
    older deprecated alias on some releases). This function inspects
    `_AGENT_PARAMS` (computed once at import time) and passes the prompt
    under whichever name the installed API expects, so every caller can just
    say "system_prompt" and not care which library actually built the graph.

    Args:
        llm: The chat model the agent will call (see `llm.get_llm()`).
        tools: LangChain tools the agent may call mid-reasoning - normally
            the list from `tools.build_tools()`.
        system_prompt: The instructions for this call, from `prompts.py` via
            `prompts.get_prompt()`.
        response_format: A pydantic model class to request native structured
            output for (see module docstring). Only actually applied if
            `SUPPORTS_NATIVE_RESPONSE_FORMAT` is true; otherwise silently
            ignored here (the caller, `run_agent_with_structured_output`,
            only passes this when it intends to use the native path).

    Returns:
        A compiled LangGraph graph (`CompiledStateGraph`). Call `.invoke({"messages": [...]})`
        on it; the result dict has a `"messages"` key and, if `response_format`
        was honored, a `"structured_response"` key holding the parsed object
        (`None` if the agent never produced one - see
        `run_agent_with_structured_output`'s fallback handling for that case).
    """
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
    """Concatenate every AI-authored message's text content from an agent
    `.invoke()` result, in order. Used both as the `raw_transcript_text`
    returned to callers (for logging/debugging and for the correction node's
    context) and as the source text for the manual structuring fallback."""
    parts = []
    for message in result.get("messages", []):
        if isinstance(message, AIMessage) and message.content:
            parts.append(message.content if isinstance(message.content, str) else str(message.content))
    return "\n".join(parts)


def _manual_structured_call(
    llm: BaseChatModel, system_prompt: str, transcript: str, output_schema: Type[T], max_retries: int
) -> T:
    """The version-robust fallback: shape a finished agent transcript into
    `output_schema` via a *separate* `llm.with_structured_output(...)` call
    (https://reference.langchain.com/python/langchain-openai/langchain_openai/chat_models/base/ChatOpenAI/with_structured_output).

    This is strictly slower than the native `response_format` path (module
    docstring) - it's a second full LLM request - so
    `run_agent_with_structured_output` only reaches this when the native
    path is unavailable/disabled, or came back with no structured response.

    Retries up to `max_retries` times on a pydantic validation failure,
    feeding the validation error back into the prompt so the model can
    correct itself, before giving up with a `RuntimeError`.
    """
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
    """Run one tool-calling agent and return a typed `output_schema` instance.

    This is the only function every agent-backed node in `nodes/*.py` calls
    to talk to the LLM - see the module docstring for why it exists and what
    problem it solves.

    ## Which path runs

    1. **Native path** (default - `pipeline_config.use_native_structured_output`,
       and only if `SUPPORTS_NATIVE_RESPONSE_FORMAT` is true for the installed
       agent API): builds the agent with `response_format=output_schema` and
       makes exactly one `.invoke()` call. If the result carries a non-`None`
       `"structured_response"`, that's returned immediately - **one LLM round
       trip** (see module docstring on `ProviderStrategy`/`ToolStrategy`).
    2. **Manual fallback**: runs the tool-calling agent *without*
       `response_format` to completion, then makes a second, separate
       `llm.with_structured_output(...)` call against the resulting
       transcript (`_manual_structured_call`) - **two LLM round trips**.
       Reached when the native path is disabled, unsupported, or (rare) ran
       but the agent never actually produced a `structured_response` - a
       warning is logged when that happens, since it means the native path
       silently doubled back to the same cost as never having it.

    Args:
        llm: The chat model to invoke (see `llm.get_llm()`).
        tools: Tools the agent may call while reasoning (see `tools.build_tools()`).
        system_prompt: Instructions for this call (see `prompts.get_prompt()`).
        user_input: The task-specific content for this call - becomes the
            single `HumanMessage` the agent starts from.
        output_schema: A pydantic `BaseModel` subclass describing the shape
            of the answer this call must produce.
        pipeline_config: Supplies `use_native_structured_output` (native vs.
            always-manual) and `structured_output_max_retries` (bound on the
            manual fallback's retry loop). If omitted, defaults to native-on
            with 2 retries - used by call sites/tests that don't have a
            config handy; real pipeline runs always pass one through (see
            `graph.run_pipeline`).

    Returns:
        A `(parsed_output, raw_transcript_text)` tuple: the validated
        `output_schema` instance, and the concatenated text of every AI
        message from the run (kept for logging and for feeding into the
        correction node's context - see `nodes/correct.py`).
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
