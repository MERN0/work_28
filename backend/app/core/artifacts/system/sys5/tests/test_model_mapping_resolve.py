"""model_mapping_resolve.py is now fully deterministic (no LLM escalation
for a factor value that doesn't cleanly match a Model_Input_Mapping row) -
these tests exercise that fast-path/unresolved behavior directly."""
from __future__ import annotations

from ..nodes import model_mapping_resolve
from ..pipeline_config import PipelineConfig
from ..schema import Factor, FactorTable, ModelInputMappingRow


class _FakeStore:
    def __init__(self, rows: list[ModelInputMappingRow]):
        self._rows = rows

    def get_model_input_mapping(self, signal: str) -> list[ModelInputMappingRow]:
        return [r for r in self._rows if r.signal == signal]


def _table() -> FactorTable:
    return FactorTable(
        feature_id="019",
        fixed_factors=[Factor(name="Direction Switch", values=["FWD", "REV"], signal_ref="MDL_DirectionSwitch")],
        variable_factors=[Factor(name="Power Control Mode", values=["P", "S", "E"], signal_ref="MDL_PwrCtrlMode")],
    )


def test_clean_match_resolves_via_fast_path(monkeypatch):
    rows = [
        ModelInputMappingRow(signal="MDL_DirectionSwitch", test_case_input="FWD", model_input="1", model_output_to_ecu="FWD_ECU"),
        ModelInputMappingRow(signal="MDL_DirectionSwitch", test_case_input="REV", model_input="0", model_output_to_ecu="REV_ECU"),
        ModelInputMappingRow(signal="MDL_PwrCtrlMode", test_case_input="P", model_input="P_VAL"),
        ModelInputMappingRow(signal="MDL_PwrCtrlMode", test_case_input="S", model_input="S_VAL"),
        ModelInputMappingRow(signal="MDL_PwrCtrlMode", test_case_input="E", model_input="E_VAL"),
    ]
    monkeypatch.setattr(model_mapping_resolve, "get_factor_table", lambda feature_id: _table())

    node = model_mapping_resolve.build(_FakeStore(rows), pipeline_config=PipelineConfig())
    state = node({"feature_id": "019"})

    resolved = state["factor_signal_resolutions"]
    assert resolved["Direction Switch::FWD"]["model_input"] == "1"
    assert resolved["Power Control Mode::E"]["model_input"] == "E_VAL"
    assert len(resolved) == 5


def test_unmatched_value_is_left_unresolved_not_guessed(monkeypatch, caplog):
    # No Model_Input_Mapping row for MDL_DirectionSwitch at all - REV/FWD
    # values cannot cleanly resolve, and must not appear in the output
    # rather than being escalated to (or guessed by) an LLM.
    rows = [
        ModelInputMappingRow(signal="MDL_PwrCtrlMode", test_case_input="P", model_input="P_VAL"),
        ModelInputMappingRow(signal="MDL_PwrCtrlMode", test_case_input="S", model_input="S_VAL"),
        ModelInputMappingRow(signal="MDL_PwrCtrlMode", test_case_input="E", model_input="E_VAL"),
    ]
    monkeypatch.setattr(model_mapping_resolve, "get_factor_table", lambda feature_id: _table())

    node = model_mapping_resolve.build(_FakeStore(rows), pipeline_config=PipelineConfig())
    state = node({"feature_id": "019"})

    resolved = state["factor_signal_resolutions"]
    assert "Direction Switch::FWD" not in resolved
    assert "Direction Switch::REV" not in resolved
    assert len(resolved) == 3  # only the three Power Control Mode values
