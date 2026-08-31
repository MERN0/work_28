"""Regression tests for a real bug hit against real input files: openpyxl
reads a numeric-looking cell (e.g. a parameter's default value, "300") as a
Python int/float, not a string. comm_matrix_extract.py, app_param_extract.py,
and io_signal_extract.py used to pass those raw values straight into
pydantic models typed as plain `str` - which pydantic v2 does NOT coerce
non-str input into - raising a ValidationError. The synthetic test fixtures
never caught this because they write every cell as an already-quoted string
literal, unlike a real .xlsx file's genuinely numeric cells. These tests use
literal Python int/float values (mirroring what openpyxl actually returns)
to reproduce and guard against the bug directly, without needing a real
input file.
"""
from __future__ import annotations

from ..nodes import app_param_extract, comm_matrix_extract, io_signal_extract
from ..pipeline_config import PipelineConfig


class _FakeStore:
    """Minimal stand-in exposing only what these nodes call on the store."""

    def __init__(self, rows: list[dict]):
        self._rows = rows

    def get_feature_marked_rows(self, sheet: str, feature_id: str) -> list[dict]:
        return self._rows

    def lookup_command_name(self, signal_name, top_k=None):
        return []


def test_app_param_extract_handles_numeric_cells():
    # Every row has a clean marker=True (the O fast-path), so extract_valid_rows
    # never escalates to the LLM - no stub needed for call_llm.
    rows = [
        {
            "Parameter ID": "TMHC_SYSRS_PARM0001",
            "Parameter Name": "Slope_Detection_Latency",
            "Parameter Description": "Time within which a slope should be detected",
            "Parameter Type": "Configuration",
            "Unit": "ms",
            "Parameter Valid Value": 300,       # real openpyxl int, not "300"
            "Parameter default value": 300.0,   # real openpyxl float
            "Parameter min Value": 0,
            "Parameter max Value": 1000,
            "Resolution": 1,
            "_marker": True, "_marker_raw": "O",
        }
    ]
    node = app_param_extract.build(_FakeStore(rows), llm=None, pipeline_config=PipelineConfig())

    state = node({"feature_id": "019"})

    params = state["app_param_valid"]
    assert len(params) == 1
    assert params[0].valid_value == "300"
    assert params[0].default_value == "300.0"
    assert params[0].min_value == "0"
    assert params[0].max_value == "1000"


def test_comm_matrix_extract_handles_numeric_cells():
    rows = [
        {
            "Signal ID": 12,                      # real openpyxl int
            "Message Name": "Main_SDO_Tx",
            "Message IDs": 1409,                  # e.g. a decimal-typed CAN id
            "Logical Signal Name": "PwrCtrlMode",
            "Signal name": "Main_TxS_0x2020_0x01",
            "Signal Description": "Power control mode",
            "_marker": True, "_marker_raw": "O",
        }
    ]
    node = comm_matrix_extract.build(_FakeStore(rows), llm=None, pipeline_config=PipelineConfig())

    state = node({"feature_id": "019"})

    signals = state["comm_matrix_valid"]
    assert len(signals) == 1
    assert signals[0].signal_id == "12"
    assert signals[0].message_ids == "1409"


def test_io_signal_extract_handles_numeric_cells():
    rows = [
        {
            "Signal ID": 5,                       # real openpyxl int
            "Logical Signal Name": "Accelerator_Sensor",
            "Signal Type": "Sensor",
            "Variants": "A1",
            "ECU": "Main",
            "Input/Output": "Input",
            "_marker": True, "_marker_raw": "O",
        }
    ]
    node = io_signal_extract.build(_FakeStore(rows), llm=None, pipeline_config=PipelineConfig())

    state = node({"feature_id": "019"})

    signals = state["io_signal_valid"]
    assert len(signals) == 1
    assert signals[0].signal_id == "5"
