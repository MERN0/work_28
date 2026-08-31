"""Single choke point for "ask the LLM to produce a typed answer" - every
LLM-backed node in `nodes/*.py` calls `call_llm()` from this module instead
of touching `langchain_core`/`langchain_openai` directly.

## Why one single-shot call, not a tool-calling agent

Earlier versions of this pipeline built a `create_agent(...)` tool-calling
loop per stage, giving the LLM read-only tools over `InMemoryWorkbookStore`
so it could look things up mid-conversation. Against this deployment's real
endpoint (an internal litellm proxy in front of a self-hosted `gpt-oss-120b`
via vLLM, not real OpenAI), that repeatedly broke in the specific place a
tool-calling loop is exposed: the *second* turn, once a completed tool call
was already in the conversation history (a `litellm.BadRequestError` -
"Message content.0 ... ValidatorIterator" - traced to a `langchain-openai`
message-content-format incompatibility with this backend across multiple
turns).

The fix is architectural, not another patch: every stage's Python code
*already* knows how to fetch or shortlist whatever context that stage's LLM
call needs (that's what `workbook_store.py`'s query methods are for) - the
LLM was never actually exploring blindly, it was just given the *option* to
look things up instead of being handed them directly. Every node now
assembles that context into the prompt itself and makes exactly ONE
`llm.with_structured_output(schema).invoke([...])` call: a single HTTP round
trip, one `SystemMessage` + one `HumanMessage` in, one parsed answer out,
never a second turn and never a `ToolMessage` - which is what makes this
immune to the multi-turn bug class above, not just a workaround for it.
`tools.py` (the `StructuredTool` wrappers this used to call) no longer
exists; nodes call `InMemoryWorkbookStore` methods directly, in Python.

Reference: https://reference.langchain.com/python/langchain-core/language_models/chat_models/BaseChatModel/#with_structured_output
- `with_structured_output` is a single-call primitive on every
`BaseChatModel`: for a tool-calling-capable model it binds one synthetic
"extract this schema" tool and forces `tool_choice`, parses that one tool
call's arguments into the given pydantic model, and returns the parsed
instance directly - no separate agent graph, no multi-turn loop.
"""
from __future__ import annotations

import time
from typing import Optional, Type, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from .logging_utils import get_logger
from .pipeline_config import PipelineConfig

T = TypeVar("T", bound=BaseModel)
_logger = get_logger(__name__)


def call_llm(
    llm: BaseChatModel,
    system_prompt: str,
    user_input: str,
    output_schema: Type[T],
    pipeline_config: Optional[PipelineConfig] = None,
) -> T:
    """Make one single-shot structured-output LLM call and return a typed
    `output_schema` instance.

    This is the only function every LLM-backed node in `nodes/*.py` calls -
    see the module docstring for why it exists as a single call rather than
    a tool-calling agent loop.

    Retries up to `pipeline_config.structured_output_max_retries` times on a
    pydantic validation failure, feeding the validation error back into the
    prompt so the model can correct itself, before giving up with a
    `RuntimeError`. This is separate from `ChatOpenAI`'s own HTTP-level
    retry/timeout handling (`pipeline_config.llm_max_retries`/
    `llm_timeout_seconds`, applied once when the client is built - see
    `llm.get_llm()`), which already covers transient network failures; this
    loop only covers the model producing a well-formed *request* but an
    invalid *answer*.

    Args:
        llm: The chat model to invoke (see `llm.get_llm()`).
        system_prompt: Instructions for this call (see `prompts.get_prompt()`).
        user_input: The task-specific content for this call, including any
            context (shortlisted candidates, valid signals, factor tables,
            ...) the caller has already assembled - becomes the single
            `HumanMessage`.
        output_schema: A pydantic `BaseModel` subclass describing the shape
            of the answer this call must produce.
        pipeline_config: Supplies `structured_output_max_retries`. If
            omitted, defaults to 2 retries - used by call sites/tests that
            don't have a config handy; real pipeline runs always pass one
            through (see `graph.run_pipeline`).

    Returns:
        A validated `output_schema` instance.
    """
    max_retries = pipeline_config.structured_output_max_retries if pipeline_config else 2
    structured_llm = llm.with_structured_output(output_schema)

    messages = [SystemMessage(system_prompt), HumanMessage(user_input)]
    last_error: Exception | None = None
    started = time.monotonic()

    for attempt in range(max_retries + 1):
        try:
            result = structured_llm.invoke(messages)
            parsed = result if isinstance(result, output_schema) else output_schema.model_validate(result)
            _logger.debug(
                "call_llm(%s) succeeded on attempt %d/%d in %.1fs",
                output_schema.__name__, attempt + 1, max_retries + 1, time.monotonic() - started,
            )
            return parsed
        except (ValidationError, ValueError) as exc:
            last_error = exc
            _logger.warning(
                "call_llm(%s) attempt %d/%d produced an invalid answer: %s",
                output_schema.__name__, attempt + 1, max_retries + 1, exc,
            )
            messages.append(
                HumanMessage(f"Your previous answer was invalid: {exc}\nPlease correct it and answer again.")
            )

    raise RuntimeError(
        f"Failed to obtain a valid {output_schema.__name__} after {max_retries + 1} attempts"
    ) from last_error
