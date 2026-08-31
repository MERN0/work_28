"""Unit tests for `call_llm()` - the single choke point every LLM-backed node
calls (see agents.py's module docstring for why it's one single-shot call,
not a tool-calling agent). No real LLM/proxy involved: the chat model's
`with_structured_output(...).invoke(...)` is stubbed."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from .. import agents
from ..pipeline_config import PipelineConfig


class _Out(BaseModel):
    value: str


class _FakeStructurer:
    def __init__(self, responses):
        self._responses = iter(responses)

    def invoke(self, messages):
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeLLM:
    def __init__(self, responses):
        self._responses = responses

    def with_structured_output(self, schema):
        return _FakeStructurer(self._responses)


def test_call_llm_returns_parsed_result_on_first_try():
    llm = _FakeLLM([_Out(value="ok")])
    result = agents.call_llm(llm, "system", "user", _Out, pipeline_config=PipelineConfig())
    assert result.value == "ok"


def test_call_llm_retries_on_validation_error_then_succeeds():
    llm = _FakeLLM([ValidationError.from_exception_data("_Out", []), _Out(value="ok-after-retry")])
    result = agents.call_llm(llm, "system", "user", _Out, pipeline_config=PipelineConfig(structured_output_max_retries=2))
    assert result.value == "ok-after-retry"


def test_call_llm_exhausts_retries_and_raises():
    llm = _FakeLLM([
        ValidationError.from_exception_data("_Out", []),
        ValidationError.from_exception_data("_Out", []),
    ])
    with pytest.raises(RuntimeError, match="Failed to obtain a valid _Out"):
        agents.call_llm(llm, "system", "user", _Out, pipeline_config=PipelineConfig(structured_output_max_retries=1))


def test_call_llm_defaults_to_two_retries_without_pipeline_config():
    llm = _FakeLLM([
        ValidationError.from_exception_data("_Out", []),
        ValidationError.from_exception_data("_Out", []),
        _Out(value="third-try"),
    ])
    result = agents.call_llm(llm, "system", "user", _Out)
    assert result.value == "third-try"
