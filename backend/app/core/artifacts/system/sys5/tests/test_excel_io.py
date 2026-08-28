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


def test_find_feature_column():
    headers = ["Signal ID", "Signal name", "001", "002", "005"]
    assert excel_io.find_feature_column(headers, "002") == 3
    assert excel_io.find_feature_column(headers, "2") == 3
    assert excel_io.find_feature_column(headers, "999") is None


def test_is_marked_valid_fast_path():
    assert excel_io.is_marked_valid("O") is True
    assert excel_io.is_marked_valid("o") is True
    assert excel_io.is_marked_valid("x") is False
    assert excel_io.is_marked_valid("X") is False
    assert excel_io.is_marked_valid("") is False
    assert excel_io.is_marked_valid(None) is False
    assert excel_io.is_marked_valid("?") is None  # ambiguous - must escalate, never silently guessed


def test_forward_fill_columns_handles_merged_cell_reads():
    matrix = [
        [1, "MDL_SWH_DIR_STATE", "FWD"],
        [None, None, "NEUTRAL"],
        [None, None, "BWD"],
        [2, "MDL_SEN_Slope_Angle", "0 deg"],
    ]
    excel_io.forward_fill_columns(matrix, [0, 1])
    assert [row[1] for row in matrix] == [
        "MDL_SWH_DIR_STATE", "MDL_SWH_DIR_STATE", "MDL_SWH_DIR_STATE", "MDL_SEN_Slope_Angle",
    ]


def test_fuzzy_equal_and_fuzzy_find():
    assert excel_io.fuzzy_equal("Config_Tol_Spd", "config_tol_spd ") is True
    assert excel_io.fuzzy_equal("Config_Tol_Spd", "Config_Tol_rpm") is False
    haystack = ["Config_Tol_Spd", "Config_Tol_Deg", "Config_Tol_rpm"]
    assert excel_io.fuzzy_find("config tol spd", haystack) == "Config_Tol_Spd"
    assert excel_io.fuzzy_find("totally unrelated text", haystack) is None
