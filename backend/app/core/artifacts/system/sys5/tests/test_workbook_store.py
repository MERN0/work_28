from __future__ import annotations

from ..workbook_store import InMemoryWorkbookStore, resolve_input_files


def _load(fixture_paths, feature_id) -> InMemoryWorkbookStore:
    return InMemoryWorkbookStore.load(fixture_paths, feature_id)


def test_resolve_input_files_matches_by_role(fixture_paths):
    resolved = resolve_input_files(
        input_folder_path="",
        req_filename="System Requirements.xlsx",
        uploaded_files=list(fixture_paths.values()),
    )
    assert resolved["requirements"] == fixture_paths["requirements"]
    assert resolved["command_list"] == fixture_paths["command_list"]
    assert resolved["configuration"] == fixture_paths["configuration"]
    assert resolved["compound_commands"] == fixture_paths["compound_commands"]
    assert resolved["keyword_library"] == fixture_paths["keyword_library"]


def test_feature_index_and_glossary(fixture_paths, feature_id):
    store = _load(fixture_paths, feature_id)
    info = store.get_feature_info(feature_id)
    assert info == {"name": "Slope Assist", "function_group": "Traction"}
    assert "MB Contactor: Main Battery Contactor" in store.get_glossary_text()


def test_requirement_rows_include_heading_and_typo_category(fixture_paths, feature_id):
    store = _load(fixture_paths, feature_id)
    rows = store.get_requirement_rows()
    categories = [r["Category"] for r in rows]
    assert "Heading" in categories
    assert "Funtional Requiremnt" in categories  # not silently normalized here - node layer decides


def test_comm_matrix_marker_fast_path_is_fully_deterministic(fixture_paths, feature_id):
    store = _load(fixture_paths, feature_id)
    rows = store.get_feature_marked_rows("comm_matrix", feature_id)
    markers = {r["Signal name"]: r["_marker"] for r in rows}
    assert markers["Main_TxS_0x2020_0x01"] is True    # clean 'O'
    assert markers["Main_TxS_0x2040_0x05"] is False   # clean 'x'
    assert markers["Disp_Rx1_Warning"] is False        # '?' - not a clean 'O', so deterministically not valid


def test_command_name_lookup(fixture_paths, feature_id):
    store = _load(fixture_paths, feature_id)
    matches = store.lookup_command_name("Main_TxS_0x2020_0x01")
    assert matches
    assert matches[0]["command_name"] == "CAN_HIL_PwrCtrlMode"


def test_tolerance_fuzzy_lookup(fixture_paths, feature_id):
    store = _load(fixture_paths, feature_id)
    tol = store.get_tolerance("config tol spd")
    assert tol is not None
    assert tol.tolerance_configuration == "Config_Tol_Spd"
    assert tol.value_positive == "0.5"
    assert tol.value_negative == "1.5"
    assert store.get_tolerance("nonexistent tolerance name") is None


def test_model_input_mapping_forward_fill(fixture_paths, feature_id):
    store = _load(fixture_paths, feature_id)
    rows = store.get_model_input_mapping("MDL_SWH_DIR_STATE")
    inputs = {r.test_case_input: r.model_input for r in rows}
    assert inputs == {"FWD": "1", "NEUTRAL": "2", "BWD": "3"}


def test_compound_command_multi_table_parsing(fixture_paths, feature_id):
    store = _load(fixture_paths, feature_id)
    power_on = store.get_compound_command("Power_On_A1")
    assert power_on is not None
    assert power_on.source_sheet == "Set"
    assert [s.keyword_line for s in power_on.steps] == ["Set MDL_PS_B48V", "Wait"]
    assert power_on.steps[0].parameter_settings == "52"
    assert power_on.steps[0].units == "V"

    key_on = store.get_compound_command("Key_On_A1")
    assert key_on is not None
    assert len(key_on.steps) == 1

    verifying = store.get_compound_command("Verifying_Power_On_A1")
    assert verifying is not None
    assert verifying.source_sheet == "Verify"
    assert verifying.steps[0].expected_value == "52"


def test_search_compound_commands_and_library(fixture_paths, feature_id):
    store = _load(fixture_paths, feature_id)
    shortlist = store.search_compound_commands("power on battery voltage", top_k=5)
    assert shortlist
    assert shortlist[0]["name"] in ("Power_On_A1", "Verifying_Power_On_A1")

    libs = store.search_library("ramp accelerator pedal", top_k=5)
    assert libs
    assert "Lib_Ramp" in libs[0]["signature"]


def test_hallucination_guardrail_exists(fixture_paths, feature_id):
    store = _load(fixture_paths, feature_id)
    assert store.exists("compound_command", "Power_On_A1") is True
    assert store.exists("compound_command", "Totally_Made_Up_Command") is False
    assert store.exists("command", "CAN_HIL_PwrCtrlMode") is True
    assert store.exists("command", "CAN_Invented_Command") is False
    assert store.exists("tolerance", "Config_Tol_Spd") is True
    assert store.exists("tolerance", "Config_Tol_Invented") is False
    assert store.exists("none", None) is True
    assert store.exists("signal", None) is False


def test_hallucination_guardrail_exists_falls_back_across_signal_and_command(fixture_paths, feature_id):
    """Regression test for a real production bug: the LLM sometimes picks a
    real name but the "wrong side" of the signal/command distinction - that's
    a plausibility issue, not a hallucination, so exists() must not fail a
    name just because it's real under the other ref_kind. A genuinely
    invented name must still fail both. (Set/Verify now cover both
    model-input and CAN/SDO-sourced signals uniformly - see schema.py - so
    this is exactly the case a Set/Verify step's target_ref hits.)"""
    store = _load(fixture_paths, feature_id)
    assert store.exists("signal", "CAN_HIL_PwrCtrlMode") is True  # a real command name, checked as ref_kind=signal
    assert store.exists("command", "Main_TxS_0x2020_0x01") is True  # a real signal name, checked as ref_kind=command
    assert store.exists("signal", "CAN_Totally_Invented_Name") is False
    assert store.exists("command", "Totally_Invented_Signal_Name") is False
