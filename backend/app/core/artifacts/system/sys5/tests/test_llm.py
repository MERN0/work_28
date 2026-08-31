from __future__ import annotations

from ..llm import get_llm
from ..pipeline_config import PipelineConfig


def test_get_llm_forces_v0_output_and_chat_completions_api():
    """Regression test for a real litellm 400 ('Message content.0 ...
    ValidatorIterator') hit mid-run against the vLLM-hosted gpt-oss-120b
    proxy once a tool-calling turn was in the conversation history - see
    llm.py's module docstring. output_version must default to 'v0' (plain
    string AIMessage content, not the >=1.0 content-block format) and
    use_responses_api must be False (this proxy is Chat-Completions-only)."""
    llm = get_llm(PipelineConfig())

    assert llm.output_version == "v0"
    assert llm.use_responses_api is False


def test_get_llm_output_version_is_configurable():
    cfg = PipelineConfig()
    cfg.llm_output_version = "v1"
    llm = get_llm(cfg)

    assert llm.output_version == "v1"
