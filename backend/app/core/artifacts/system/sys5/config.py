"""Settings derived from the `config` dict handed to sys5.generate().

Nothing here is pre-existing infrastructure - `Settings` is a plain object we
construct ourselves, so sys5.py is free to stash extra attributes on it
(e.g. `.timestamp`) beyond what the frozen zip-writing block reads.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Settings:
    project_name: str
    username: str
    version: str
    domain: str
    artifact: str
    model: str
    input_folder_path: str
    output_folder_path: str
    output_dir: str
    uploaded_files: list
    req_filename: str
    req_sheet_name: str
    agent_overrides: dict[str, str] = field(default_factory=dict)
    timestamp: str = ""  # populated by sys5.generate() before the frozen zip block runs

    @classmethod
    def from_config(cls, config: dict) -> "Settings":
        agent_overrides: dict[str, str] = {}
        for entry in config.get("agent_chain", []) or []:
            name = entry.get("agent_name")
            prompt_content = entry.get("prompt_content")
            if name and prompt_content:
                agent_overrides[name] = prompt_content

        return cls(
            project_name=config["project_name"],
            username=config.get("username", ""),
            version=config.get("version", ""),
            domain=config.get("domain", ""),
            artifact=config.get("artifact", "SYS5"),
            model=config.get("model", ""),
            input_folder_path=config["input_folder_path"],
            output_folder_path=config.get("output_folder_path", config.get("output_dir", "")),
            output_dir=config["output_dir"],
            uploaded_files=config.get("uploaded_files", []) or [],
            req_filename=config["req_filename"],
            req_sheet_name=config["req_sheet_name"],
            agent_overrides=agent_overrides,
        )
