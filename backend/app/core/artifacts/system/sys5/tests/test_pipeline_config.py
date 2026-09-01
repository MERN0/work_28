from __future__ import annotations

import json

from ..pipeline_config import PipelineConfig


def test_defaults_load_without_a_file():
    config = PipelineConfig.load(path="/nonexistent/path/pipeline_config.json")
    assert config.llm_model == "llm-1-gpt-osx-120b"
    assert config.max_test_cases_per_requirement == 5
    assert config.category_match_threshold == 95


def test_bundled_json_file_matches_dataclass_defaults():
    # pipeline_config.json ships with values equal to the dataclass defaults
    # (the "one place" the user edits) - loading it should be a no-op vs. no file.
    default = PipelineConfig()
    from_file = PipelineConfig.load()
    assert from_file.as_dict() == default.as_dict()


def test_json_file_overrides_apply(tmp_path):
    path = tmp_path / "custom_pipeline_config.json"
    path.write_text(json.dumps({"max_test_cases_per_requirement": 8, "category_match_threshold": 90}))
    config = PipelineConfig.load(path=str(path))
    assert config.max_test_cases_per_requirement == 8
    assert config.category_match_threshold == 90
    assert config.llm_model == "llm-1-gpt-osx-120b"  # untouched keys keep the dataclass default


def test_unknown_json_key_is_ignored_not_fatal(tmp_path):
    path = tmp_path / "custom_pipeline_config.json"
    path.write_text(json.dumps({"max_test_cases_per_requirement": 2, "totally_made_up_key": 123}))
    config = PipelineConfig.load(path=str(path))
    assert config.max_test_cases_per_requirement == 2
    assert config._unknown_keys == {"totally_made_up_key"}


def test_env_var_overrides_llm_connection(tmp_path, monkeypatch):
    path = tmp_path / "pipeline_config.json"
    path.write_text(json.dumps({}))
    monkeypatch.setenv("SYS5_LLM_MODEL", "custom-model")
    monkeypatch.setenv("SYS5_LLM_MAX_RETRIES", "9")
    config = PipelineConfig.load(path=str(path))
    assert config.llm_model == "custom-model"
    assert config.llm_max_retries == 9


def test_path_env_var_is_honored(tmp_path, monkeypatch):
    path = tmp_path / "alt_pipeline_config.json"
    path.write_text(json.dumps({"max_test_cases_per_requirement": 1}))
    monkeypatch.setenv("SYS5_PIPELINE_CONFIG_PATH", str(path))
    config = PipelineConfig.load()
    assert config.max_test_cases_per_requirement == 1
