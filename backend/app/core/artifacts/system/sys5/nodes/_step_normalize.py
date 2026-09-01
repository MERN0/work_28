"""Shared post-processing applied to every LLM-generated TestStep, in
generate.py and correct.py alike, right after the LLM call returns and
before hallucination_check ever sees the steps. Three real production bugs,
one normalization pass - order matters (each one feeds the next):

1. ref_kind: never trust the LLM's own answer - `keyword` alone determines
   it deterministically (see schema.derive_ref_kind's docstring for the bug
   this closes: a step's keyword and ref_kind could otherwise disagree,
   sending hallucination_check to check a real name against the wrong
   candidate pool).
2. target_ref: replaced with its resolved canonical spelling from the
   source data (see InMemoryWorkbookStore.resolve_ref's docstring for the
   bug this closes - a malformed-but-fuzzy-matching name like 'CAN HIL
   HMode', spaces instead of underscores, used to pass the hallucination
   guardrail unchanged and ship in the output workbook exactly as
   misspelled, since `exists()` only ever confirmed a match existed without
   ever writing the real spelling back).
3. step_text: derived from the now-canonical keyword+target_ref (see
   schema.derive_step_text's docstring) - must run AFTER step 2, so a step
   text like "Set CAN_HIL_HMode" is built from the corrected name, not the
   LLM's original malformed one.
"""
from __future__ import annotations

from ..schema import TestStep, derive_ref_kind, derive_step_text
from ..workbook_store import InMemoryWorkbookStore


def normalize_steps(steps: list[TestStep], store: InMemoryWorkbookStore | None) -> list[TestStep]:
    normalized = []
    for s in steps:
        ref_kind = derive_ref_kind(s.keyword)
        target_ref = s.target_ref
        if store is not None and ref_kind != "none" and target_ref:
            target_ref = store.resolve_ref(ref_kind, target_ref) or target_ref
        normalized.append(
            s.model_copy(update={
                "ref_kind": ref_kind,
                "target_ref": target_ref,
                "step_text": derive_step_text(s.keyword, target_ref, s.step_text),
            })
        )
    return normalized
