"""Unit tests for the native-response_format vs. manual two-call structuring
logic in agents.py - the main lever for cutting LLM round trips (item 3). No
real LLM/proxy involved: make_agent and llm.with_structured_output are
stubbed."""
from __future__ import annotations

from pydantic import BaseModel

from .. import agents
from ..pipeline_config import PipelineConfig


class _Out(BaseModel):
    value: str


def test_native_path_used_when_structured_response_present(monkeypatch):
    class _FakeAgent:
        def invoke(self, payload):
            return {"messages": [], "structured_response": _Out(value="native")}

    monkeypatch.setattr(agents, "make_agent", lambda llm, tools, prompt, response_format=None: _FakeAgent())
    monkeypatch.setattr(agents, "SUPPORTS_NATIVE_RESPONSE_FORMAT", True)

    result, _transcript = agents.run_agent_with_structured_output(
        llm=object(), tools=[], system_prompt="p", user_input="u", output_schema=_Out,
        pipeline_config=PipelineConfig(use_native_structured_output=True),
    )
    assert result.value == "native"


def test_falls_back_to_manual_when_native_yields_no_structured_response(monkeypatch):
    call_log: list[str] = []

    class _FakeAgentNoStructured:
        def invoke(self, payload):
            call_log.append("native")
            return {"messages": []}

    class _FakeAgentManual:
        def invoke(self, payload):
            call_log.append("manual")
            return {"messages": []}

    def fake_make_agent(llm, tools, prompt, response_format=None):
        return _FakeAgentNoStructured() if response_format is not None else _FakeAgentManual()

    monkeypatch.setattr(agents, "make_agent", fake_make_agent)
    monkeypatch.setattr(agents, "SUPPORTS_NATIVE_RESPONSE_FORMAT", True)

    class _FakeStructurer:
        def invoke(self, prompt):
            return _Out(value="manual")

    class _FakeLLM:
        def with_structured_output(self, schema):
            return _FakeStructurer()

    result, _transcript = agents.run_agent_with_structured_output(
        llm=_FakeLLM(), tools=[], system_prompt="p", user_input="u", output_schema=_Out,
        pipeline_config=PipelineConfig(use_native_structured_output=True),
    )
    assert result.value == "manual"
    assert call_log == ["native", "manual"]  # native attempted first, manual only as fallback


def test_disabling_native_skips_straight_to_manual_path(monkeypatch):
    seen_response_formats: list[object] = []

    def fake_make_agent(llm, tools, prompt, response_format=None):
        seen_response_formats.append(response_format)

        class _Agent:
            def invoke(self, payload):
                return {"messages": []}

        return _Agent()

    monkeypatch.setattr(agents, "make_agent", fake_make_agent)

    class _FakeStructurer:
        def invoke(self, prompt):
            return _Out(value="manual-only")

    class _FakeLLM:
        def with_structured_output(self, schema):
            return _FakeStructurer()

    result, _transcript = agents.run_agent_with_structured_output(
        llm=_FakeLLM(), tools=[], system_prompt="p", user_input="u", output_schema=_Out,
        pipeline_config=PipelineConfig(use_native_structured_output=False),
    )
    assert result.value == "manual-only"
    assert seen_response_formats == [None]  # never asked make_agent for native structured output
