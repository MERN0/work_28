"""Inner subgraph node: decide clean vs. flagged and produce the final
TestCase for this test-pattern row (the 1:1 mapping's terminal node)."""
from __future__ import annotations

from ..state import TestCaseState


def build():
    def node(state: TestCaseState) -> TestCaseState:
        test_case = state["test_case"]
        hallucination_ok = state.get("hallucination_ok", True)
        pass1 = state.get("pass1_result")
        pass2 = state.get("pass2_result")

        problems = list(state.get("issues", []))
        for result in (pass1, pass2):
            if result and not result.passed:
                problems.extend(f"[{result.rubric}] {issue.message}" for issue in result.issues)

        clean = hallucination_ok and (pass1 is None or pass1.passed) and (pass2 is None or pass2.passed)
        if clean:
            final = test_case.model_copy(update={"status": "clean", "flag_reason": None})
        else:
            summary = "; ".join(problems) or "unresolved validation issue"
            final = test_case.model_copy(update={"status": "flagged", "flag_reason": summary})

        return {**state, "final_test_case": final}

    return node
