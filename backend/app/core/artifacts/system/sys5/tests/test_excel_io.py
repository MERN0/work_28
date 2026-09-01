from __future__ import annotations

from .. import excel_io


def test_norm_collapses_whitespace():
    assert excel_io._norm("  Signal   Name \n") == "Signal Name"
    assert excel_io._norm(None) == ""


def test_find_header_row_skips_title_rows():
    matrix = [
        ["Some Title Banner", None, None],
        [None, None, None],
        ["Requirement ID", "Requirement Description", "Category"],
        ["REQ-1", "desc", "Functional Requirement"],
    ]
    assert excel_io.find_header_row(matrix, ["Requirement ID", "Category"]) == 2


def test_resolve_columns_handles_typos_and_whitespace():
    headers = ["Requirement  ID", "Requirement Descriptin", "Categroy"]
    resolved = excel_io.resolve_columns(headers, ["Requirement ID", "Requirement Description", "Category"], threshold=70)
    assert resolved["Requirement ID"] == 0
    assert resolved["Requirement Description"] == 1
    assert resolved["Category"] == 2


def test_normalize_feature_id_variants():
    assert excel_io.normalize_feature_id("005") == "005"
    assert excel_io.normalize_feature_id(5) == "005"
    assert excel_io.normalize_feature_id(" Feature_005 ") == "005"
    assert excel_io.normalize_feature_id("") is None
    assert excel_io.normalize_feature_id(None) is None


def test_rows_as_dicts_skips_blank_rows():
    matrix = [
        ["Requirement ID", "Category"],
        ["REQ-1", "Functional Requirement"],
        [None, None],
        ["REQ-2", "Heading"],
    ]
    col_map = excel_io.resolve_columns(matrix[0], ["Requirement ID", "Category"])
    rows = excel_io.rows_as_dicts(matrix, 0, col_map)
    assert [r["Requirement ID"] for r in rows] == ["REQ-1", "REQ-2"]


def test_fuzzy_find():
    haystack = ["Functional Requirement", "NonFunctional Requirement", "Heading"]
    assert excel_io.fuzzy_find("functional requirement", haystack) == "Functional Requirement"
    assert excel_io.fuzzy_find("totally unrelated text", haystack) is None
