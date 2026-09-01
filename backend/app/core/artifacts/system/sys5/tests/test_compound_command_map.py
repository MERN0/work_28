"""compound_command_map.py is now fully deterministic (no LLM selection call)
- it keeps the top-scoring keyword-overlap candidates outright, capped and
threshold-filtered by pipeline_config. These tests exercise that selection
logic directly, without any LLM."""
from __future__ import annotations

from ..nodes import compound_command_map
from ..pipeline_config import PipelineConfig
from ..schema import Requirement


class _FakeStore:
    """Returns fixed, pre-scored candidate lists regardless of the query -
    enough to prove the node applies the cap/threshold correctly and never
    calls anything beyond search_compound_commands/search_library."""

    def __init__(self, compound_candidates: list[dict], library_candidates: list[dict]):
        self._compound = compound_candidates
        self._library = library_candidates

    def search_compound_commands(self, query, top_k=None):
        return self._compound[: top_k or len(self._compound)]

    def search_library(self, query, top_k=None):
        return self._library[: top_k or len(self._library)]


def _req(req_id="REQ-1") -> Requirement:
    return Requirement(req_id=req_id, description="desc", category="Functional Requirement")


def test_selects_only_candidates_at_or_above_threshold():
    compound = [
        {"name": "Compound_A", "score": 90},
        {"name": "Compound_B", "score": 44},  # just under the default 45 threshold
    ]
    library = [{"signature": "Lib_Ramp Signal_Name(Start=X)", "score": 60}]
    store = _FakeStore(compound, library)

    node = compound_command_map.build(store, pipeline_config=PipelineConfig())
    state = node({"requirements": [_req()]})

    selections = state["compound_selections"]["REQ-1"]
    assert [c["name"] for c in selections["compound_commands"]] == ["Compound_A"]
    assert [l["name"] for l in selections["library_calls"]] == ["Lib_Ramp Signal_Name(Start=X)"]


def test_caps_selection_count_via_max_selected():
    compound = [{"name": f"Compound_{i}", "score": 100 - i} for i in range(10)]
    store = _FakeStore(compound, [])

    config = PipelineConfig(compound_command_max_selected=3, compound_command_select_threshold=0)
    node = compound_command_map.build(store, pipeline_config=config)
    state = node({"requirements": [_req()]})

    selected = state["compound_selections"]["REQ-1"]["compound_commands"]
    assert [c["name"] for c in selected] == ["Compound_0", "Compound_1", "Compound_2"]


def test_no_candidates_above_threshold_yields_empty_selection():
    store = _FakeStore([{"name": "Compound_A", "score": 10}], [{"signature": "Lib_X()", "score": 5}])

    node = compound_command_map.build(store, pipeline_config=PipelineConfig())
    state = node({"requirements": [_req()]})

    selections = state["compound_selections"]["REQ-1"]
    assert selections == {"compound_commands": [], "library_calls": []}
