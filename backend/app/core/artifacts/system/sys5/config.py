"""Settings derived from the `config` dict handed to sys5.generate().

Nothing here is pre-existing infrastructure - `Settings` is a plain object we
construct ourselves.
"""
from __future__ import annotations

from dataclasses import dataclass


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

    @classmethod
    def from_config(cls, config: dict) -> "Settings":
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
        )
