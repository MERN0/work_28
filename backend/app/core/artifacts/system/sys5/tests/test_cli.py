from __future__ import annotations

import pytest

from .. import cli


def test_build_config_from_individual_file_paths(fixture_paths):
    args = cli._parse_args(
        [
            "--requirements", fixture_paths["requirements"],
            "--command-list", fixture_paths["command_list"],
            "--configuration", fixture_paths["configuration"],
            "--compound-commands", fixture_paths["compound_commands"],
            "--keyword-library", fixture_paths["keyword_library"],
            "--feature-id", "002",
            "--output-dir", "/tmp/sys5-cli-test-output",
        ]
    )
    config = cli.build_config(args)

    assert config["req_sheet_name"] == "002"
    assert config["output_dir"] == "/tmp/sys5-cli-test-output"
    assert set(config["uploaded_files"]) == set(fixture_paths.values())
    assert config["req_filename"] == "System Requirements.xlsx"


def test_build_config_from_input_dir_only(tmp_path):
    args = cli._parse_args(
        ["--input-dir", str(tmp_path), "--feature-id", "019", "--output-dir", str(tmp_path / "out")]
    )
    config = cli.build_config(args)

    assert config["input_folder_path"] == str(tmp_path)
    assert config["uploaded_files"] == []
    assert config["req_filename"] == ""


def test_build_config_rejects_missing_file():
    args = cli._parse_args(
        ["--requirements", "/nonexistent/req.xlsx", "--feature-id", "019", "--output-dir", "/tmp/out"]
    )
    with pytest.raises(SystemExit):
        cli.build_config(args)


def test_build_config_requires_some_input_source():
    args = cli._parse_args(["--feature-id", "019", "--output-dir", "/tmp/out"])
    with pytest.raises(SystemExit):
        cli.build_config(args)
