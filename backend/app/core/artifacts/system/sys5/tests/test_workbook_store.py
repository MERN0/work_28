from __future__ import annotations

import pytest

from ..workbook_store import InMemoryWorkbookStore, MissingInputFileError, resolve_requirements_file


def _load(fixture_paths, feature_id) -> InMemoryWorkbookStore:
    return InMemoryWorkbookStore.load(fixture_paths["requirements"], feature_id)


def test_resolve_requirements_file_matches_by_exact_filename(fixture_paths):
    resolved = resolve_requirements_file(
        input_folder_path="", req_filename="System Requirements.xlsx", uploaded_files=[fixture_paths["requirements"]],
    )
    assert resolved == fixture_paths["requirements"]


def test_resolve_requirements_file_falls_back_to_sole_candidate(fixture_paths):
    resolved = resolve_requirements_file(
        input_folder_path="", req_filename="", uploaded_files=[fixture_paths["requirements"]],
    )
    assert resolved == fixture_paths["requirements"]


def test_resolve_requirements_file_raises_when_nothing_found():
    with pytest.raises(MissingInputFileError):
        resolve_requirements_file(input_folder_path="", req_filename="", uploaded_files=[])


def test_resolve_requirements_file_raises_when_ambiguous(fixture_paths, tmp_path):
    other = tmp_path / "Some Other Workbook.xlsx"
    other.write_bytes(b"")
    with pytest.raises(MissingInputFileError):
        resolve_requirements_file(
            input_folder_path="", req_filename="", uploaded_files=[fixture_paths["requirements"], str(other)],
        )


def test_feature_index(fixture_paths, feature_id):
    store = _load(fixture_paths, feature_id)
    info = store.get_feature_info(feature_id)
    assert info == {"name": "Slope Assist", "function_group": "Traction"}


def test_requirement_rows_include_heading_and_typo_category(fixture_paths, feature_id):
    store = _load(fixture_paths, feature_id)
    rows = store.get_requirement_rows()
    categories = [r["Category"] for r in rows]
    assert "Heading" in categories
    assert "Funtional Requiremnt" in categories  # not silently normalized here - node layer decides
