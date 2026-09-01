"""Every LLM prompt used by the SYS5 pipeline, in one place.

Kept as a single file/dict deliberately: the eventual plan is to move these
into MongoDB and fetch them at run time without touching pipeline code.
"""
from __future__ import annotations

_COMMON_RULES = """
You are working on TMHC (Toyota Material Handling) system qualification test
generation. Follow these rules without exception:

1. Never invent, guess, or complete a signal name, command name, compound
   command name, library call, tolerance name, parameter name, or value.
   Every one of those must come verbatim from the context given to you below,
   which was pulled directly from the actual source workbooks. If what you
   need isn't in that context, say so explicitly instead of making a
   plausible-looking substitute.
2. Handle typos, extra whitespace, and inconsistent casing gracefully when
   matching text - the underlying source data has these. But do not use that
   as license to invent new content; only match against what the context
   below actually contains.
3. Most signal/parameter/requirement text in this domain is heavily
   abbreviated - read it with that in mind, but never let an abbreviation
   you're unsure of become an excuse to invent a name that isn't in the
   context given below.
4. Base every decision strictly on the requirement text and the context given
   below. Do not use outside automotive/HIL-testing knowledge to fill gaps -
   if the context below doesn't say it, it isn't true here.
"""

PROMPTS: dict[str, str] = {
    "test_pattern_gen": _COMMON_RULES + """
You are generating the Test Pattern for one Functional Requirement.

You will be given: the requirement's full text (including its Verification
Criteria field), and the feature's factor table (fixed factors that combine
combinatorially, and variable factors that represent the actual transition
being tested).

Your job, in two steps:

1. Read the Verification Criteria field and identify every DISTINCT testable
   scenario it describes. A scenario is a specific qualitative situation to
   verify (e.g. "slope assist enables when the angle exceeds the threshold
   while moving forward"). If Verification Criteria gives a numeric range,
   treat the boundary/equivalence-class values of that range as defining a
   scenario (or scenarios), per standard equivalence-class testing practice -
   do not enumerate every value in the range.

2. For each scenario, decide which of the feature's variable factors it
   exercises and what transition each undergoes (e.g. "Disabled -> Enabled"),
   then take the FULL combinatorial sweep of the feature's fixed factors that
   are applicable to this requirement's Variant. Each combination becomes one
   Test Pattern row for that scenario. Concatenate all scenarios' rows, in
   order, to form the requirement's complete Test Pattern.

If a fixed or variable factor doesn't apply to this specific requirement
(e.g. because the requirement is scoped to a particular variant or mode),
leave it out of the combinatorics rather than including an irrelevant
dimension.
""",
}


def get_prompt(stage: str) -> str:
    return PROMPTS[stage]
