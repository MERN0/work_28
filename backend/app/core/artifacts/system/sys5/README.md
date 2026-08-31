# SYS5 — System Qualification Test Case Generator

Reads a System Requirements workbook plus four supporting reference
workbooks, and produces a System Qualification Test Case workbook (zipped)
for one feature at a time. Everything lives in this one directory
(`backend/app/core/artifacts/system/sys5/`) — no shared code outside it.

This file is the map. Read it once before touching the code; each module
still carries its own detailed docstring for the how, this file is for the
**why** and **how the pieces fit together**.

## 1. What actually happens when you call `generate(config)`

```
config dict (from the harness)
        │
        ▼
  sys5.py: generate()
        │  Settings.from_config(config)      ── config.py
        │  PipelineConfig.load()              ── pipeline_config.py / .json
        │  configure_logging(...)             ── logging_utils.py
        ▼
  graph.py: run_pipeline(settings, pipeline_config)
        │
        │  1. load_inputs()                   ── nodes/load_inputs.py
        │       resolve_input_files()          + InMemoryWorkbookStore.load()  ── workbook_store.py
        │       (every input .xlsx is parsed from disk ONCE, here)
        │
        │  2. get_llm() + build_tools(store)  ── llm.py, tools.py
        │
        │  3. the OUTER StateGraph runs, one node per pipeline stage:
        │       feature_index → requirements_extract → comm_matrix_extract
        │       → app_param_extract → io_signal_extract → test_pattern_gen
        │       → model_mapping_resolve → compound_command_map
        │       → test_case_loop → output_assemble
        │     (see §3 below for what each one does)
        │
        │       test_case_loop invokes an INNER StateGraph once per
        │       test-pattern row — this is where each individual test case
        │       gets generated, hallucination-checked, validated, and
        │       (if needed) corrected. See §4.
        ▼
  sys5.py: generate() resumes
        │  writes the output .xlsx (xlsx_writer.py, called from
        │  nodes/output_assemble.py) and zips settings.output_dir
        │  (the "Donot change" block — this part is a frozen contract,
        │  never edit it)
        ▼
  returns the zip path
```

Nothing in this pipeline is "confusing magic" — it's a fixed sequence of
Python function calls, some of which happen to call an LLM. If you're lost,
find the stage name in the log output (every stage logs `-> stage_name` /
`<- stage_name done in Xs`, see §6) and go read that one node file.

## 2. The two config surfaces — don't confuse them

| | `config` dict (→ `config.py`'s `Settings`) | `pipeline_config.json` (→ `pipeline_config.py`'s `PipelineConfig`) |
|---|---|---|
| Who sets it | The calling harness, per run (`generate(config)`'s argument) | You, by hand-editing the JSON file |
| What it holds | *This run's* project name, file paths, which feature/sheet to process, per-agent prompt overrides | Every reusable engineering knob: LLM model/credentials/retries, every fuzzy-match threshold, shortlist sizes, concurrency, logging |
| Where it's read | `Settings.from_config(config)` in `sys5.generate()` | `PipelineConfig.load()` in `sys5.generate()` |

If you want to change how *this specific request* is processed (which
feature, which files), that comes from the caller's `config` dict — nothing
to edit here. If you want to change how the pipeline *behaves* (faster/
slower, stricter/looser matching, which model), edit `pipeline_config.json`.
The `.py` file next to it only defines the schema and a fallback if the JSON
is missing — see that module's own docstring for the full load order.

## 3. Module map

```
sys5.py                 entry point: generate(config) -> zip path. Also runnable
                         standalone (`python sys5.py config.json`) - see its docstring
                         for the PEP 366 trick that makes both modes work.
config.py                Settings: the per-run config dict, typed.
pipeline_config.py/.json PipelineConfig: engineering knobs, one place to edit (§2).
logging_utils.py        configure_logging() / get_logger() / stage_timer() - every
                         node's log lines go through this.

excel_io.py              Judgment-free Excel primitives: read a sheet, find a header
                         row, fuzzy-match column names, forward-fill merged cells.
                         Never decides what data MEANS - only reads it honestly.
workbook_store.py        InMemoryWorkbookStore: parses all 5 input workbooks ONCE
                         (via excel_io.py) into an in-memory "virtual backend" that
                         every tool/node queries instead of touching disk again.
                         Also: the anti-hallucination guardrail, store.exists().
factors.py                Human-supplied per-feature factor tables (Truck Size, Power
                         Control Mode, ...) - domain knowledge that can't be read out
                         of the Excel files. Fails fast (MissingFactorTableError) for
                         an unregistered feature rather than letting an LLM guess.

llm.py                   Builds the one ChatOpenAI client the run shares.
agents.py                 The only place that talks to langchain's agent API
                         (create_agent) - version-adapter + the native-vs-manual
                         structured-output logic that halves LLM round trips.
tools.py                  @tool-wrapped, read-only functions over InMemoryWorkbookStore -
                         the ONLY way an LLM agent ever sees source data.
prompts.py                Every prompt template, in one dict, keyed by stage name.

state.py                  The two TypedDicts (PipelineState, TestCaseState) threaded
                         through the outer and inner LangGraph graphs.
schema.py                  Every pydantic model: parsed-row shapes, TestCase/TestStep,
                         validation results, the run manifest.
graph.py                   Builds and wires both StateGraphs (outer pipeline, inner
                         per-test-case loop) and run_pipeline(), the top-level driver.

nodes/                     One module per pipeline stage - see §3 for the outer
                         stages and §4 for the inner (per-test-case) ones.

xlsx_writer.py             Writes the final output workbook (5 sheets), including the
                         merged-cell / blank-row layout rules from the real reference
                         example.

tests/                     pytest suite + synthetic fixture workbooks. No real LLM
                         calls anywhere in it - see tests/README notes below and each
                         test file's own docstring for what's actually exercised.
```

## 4. The outer pipeline stages (`graph.py::_build_outer_graph`)

Each stage is a LangGraph node — a plain function `PipelineState -> PipelineState`
(https://docs.langchain.com/oss/python/langgraph/graph-api). They run in a
fixed linear order (no branching at this level); `graph.py` wires the edges
explicitly rather than relying on any implicit ordering.

| Stage | File | Deterministic or LLM? |
|---|---|---|
| `feature_index` | `nodes/feature_index.py` | Deterministic - exact Index-sheet lookup |
| `requirements_extract` | `nodes/requirements_extract.py` | Hybrid - fuzzy fast-path, LLM only for ambiguous `Category` values |
| `comm_matrix_extract` / `app_param_extract` / `io_signal_extract` | `nodes/*_extract.py` + shared `nodes/_marker_extract.py` | Hybrid - fast-path on a clean `O`/`x` marker, LLM only for ambiguous cells |
| `test_pattern_gen` | `nodes/test_pattern_gen.py` | LLM plans scenarios; Python does the actual combinatorics (deterministic) |
| `model_mapping_resolve` | `nodes/model_mapping_resolve.py` | Hybrid - exact/fuzzy lookup first, LLM only for what doesn't resolve |
| `compound_command_map` | `nodes/compound_command_map.py` | LLM selects, after a deterministic keyword-overlap shortlist narrows ~700 candidates down (see §7) |
| `test_case_loop` | `nodes/test_case_loop.py` | Orchestrates the inner subgraph (§5) once per test-pattern row, concurrently |
| `output_assemble` | `nodes/output_assemble.py` | Deterministic - writes the output workbook via `xlsx_writer.py` |

"Hybrid" nodes never let an LLM *invent* an answer for something Python can
already tell for certain (a literal `O`/`x`, an exact string match) — the LLM
is only asked when the deterministic check is genuinely ambiguous. This is
the load-bearing design principle across the whole codebase: **plain Python
for mechanical fact, an LLM only for actual judgment calls.**

## 5. The inner per-test-case subgraph (`graph.py::_build_inner_test_case_graph`)

`test_case_loop` invokes this **once per test-pattern row** (e.g. 24 times
for a 24-row Test Pattern), each with its own fresh `TestCaseState`. Rows are
independent, so up to `pipeline_config.max_concurrent_test_cases` run at once
via a `ThreadPoolExecutor` (see `nodes/test_case_loop.py`).

```
        generate
           │
    hallucination_check ──(fail, no correction yet)──► correct ─┐
           │                                                     │
     (ok / already corrected once)                               │
           │                                                     │
      validate  (one node if pipeline_config.combine_validation_passes,      │
    (pass1+pass2)  else two separate nodes validate_pass1 → validate_pass2)  │
           │                                                     │
   (both passed, or already corrected once) ──► finalize_pass    │
           │                                        ▲            │
     (either failed, no correction yet) ── correct ──┘◄──────────┘
```

- `hallucination_check` (`nodes/hallucination_check.py`) is **deterministic** —
  it checks every step's referenced signal/command/compound-command/tolerance/
  library call actually exists in the parsed source data
  (`InMemoryWorkbookStore.exists()`). No LLM call.
- `validate` / `validate_pass1` + `validate_pass2` (`nodes/validate.py`) are
  two *distinct rubrics* — requirement-fidelity and engineering-plausibility —
  always both applied, never short-circuited on the first failure, so a
  single correction attempt sees the combined issue list. Combined into one
  LLM call by default (`pipeline_config.combine_validation_passes`); set that
  to `false` to go back to two separate calls.
- `correct` (`nodes/correct.py`) runs **at most once** per row (`correction_attempted`
  flag in state) and always routes back through `hallucination_check`, so the
  corrected version goes through the identical gate a fresh generation would.
- `finalize_pass` (`nodes/finalize_pass.py`) marks the test case `"clean"` or
  `"flagged"` (with the reason) — a flagged case still ships in the output,
  it's never silently dropped, so the 1:1 test-pattern-to-test-case mapping
  always holds even when something couldn't be fully resolved.

## 6. Logging

Every stage above (and the per-requirement/per-row work inside them) logs
through `logging_utils.py`: `-> stage (context)` on entry, `<- stage done in
Xs` on success, or a full exception on failure. Output goes to the console
**and** to `<output_dir>/sys5_run.log`, so a completed run leaves a permanent,
timestamped record of exactly what happened and how long each part took —
check that file first when something looks wrong or slow.

## 7. Where an LLM could pick the wrong thing (know the failure mode)

`compound_command_map` and the library-call selection inside `generate` rely
on **lexical** keyword-overlap search (`rapidfuzz.fuzz.token_set_ratio` in
`workbook_store.py`'s `search_compound_commands`/`search_library`) to narrow
~700 compound commands / ~50 libraries down to a shortlist the LLM actually
reads. This is keyword overlap, not semantic similarity — if a requirement's
wording shares no vocabulary with the right command's name/steps, that
command may never make the shortlist, and no amount of LLM judgment
afterward recovers from a candidate it never saw. There is currently no
embedding/semantic fallback. Everything downstream of a *selected* name is
still hallucination-checked (§5) — so a wrong-but-real command can pass that
check; only the fidelity/plausibility validation might catch it being the
wrong choice for the requirement, and only if it happens to notice.

Existence checks (does this exact signal/tolerance/command name occur in the
source data at all) are a different, much safer mechanism: `store.exists()`
uses a *strict* fuzzy threshold (`pipeline_config.hallucination_match_threshold`,
default 92) specifically tuned so that short, similarly-prefixed codes (e.g.
`Config_Tol_Spd` vs. `Config_Tol_rpm`, which score ~86 on a looser scorer)
don't cross-match each other.

## 8. Running the tests

```bash
cd backend
pip install -r requirements.txt
python -m pytest app/core/artifacts/system/sys5/tests -q
```

No test in this suite reaches the real LLM proxy (it's an internal-only IP,
unreachable outside the deployment environment). What *is* covered without
one: Excel parsing/fuzzy-matching (`test_excel_io.py`, `test_workbook_store.py`),
output layout (`test_xlsx_writer.py`), the validation/correction routing
logic as pure functions (`test_graph_routing.py`), both graphs' structural
wiring (`test_graph_build.py`), the native-vs-manual structured-output
fallback logic with a stub agent (`test_agents.py`), the concurrent
test-case loop's ordering/crash-safety with a stub subgraph
(`test_test_case_loop.py`), and `pipeline_config.py`'s load/override chain
(`test_pipeline_config.py`). A real end-to-end run (real Excel files, real
LLM) can only be exercised in the deployed environment.

## 9. Codebase audit notes (deprecated APIs, dead code, simplifications)

From a pass that checked every LangChain/LangGraph API call against current
documentation (via the `docs-langchain`/`reference-langchain` MCP tools, not
memory) and grepped for unused code:

**Deprecated API found and handled**: `langgraph.prebuilt.create_react_agent`
carries an explicit deprecation notice in its own reference page, pointing at
`langchain.agents.create_agent` (https://docs.langchain.com/oss/python/migrate/langgraph-v1).
`agents.py` already tries `create_agent` first and only imports the
deprecated function as a fallback if that import fails - confirmed live in
this environment that `AGENT_API == "langchain.agents.create_agent"`, so the
deprecated path is dormant here, kept only so this module doesn't hard-fail
on an older `langgraph`-only install. See `agents.py`'s module docstring.

**Outdated (not deprecated, but superseded) parameter names fixed**:
`llm.py` was constructing `ChatOpenAI(openai_api_key=..., openai_api_base=...,
request_timeout=...)` - old aliases that still work today via Pydantic
backwards-compatibility, but the current documented constructor parameters
are `api_key`, `base_url`, and `timeout`
(https://reference.langchain.com/python/langchain-openai/langchain_openai/chat_models/base/ChatOpenAI).
Updated to match.

**Confirmed NOT deprecated** (checked because they looked like candidates):
`StructuredTool.from_function` (tools.py) - still the documented mechanism
for wrapping a dynamically-built closure as a tool, see tools.py's own
docstring for why it's the right choice here over the simpler `@tool`
decorator. Pydantic v2 usage throughout (`model_dump`/`model_validate`/
`model_copy`, no `.dict()`/`.json()`/v1 shims) - already current.

**Dead code removed**: `custom_keywords` (parsed from the "Custom Keyword &
Library Details" sheet into a `CustomKeywordEntry` model) was stored on
`InMemoryWorkbookStore` but had zero consumers anywhere in the pipeline -
`grep` confirmed no tool, node, or prompt ever read it. Removed both the
loading code and the now-unused pydantic model.

**Half-wired feature fixed, not removed**: `heading_info` (Heading/
Information rows from the requirement sheet) was computed by
`requirements_extract` and threaded into `PipelineState`, but - unlike
`custom_keywords` - the original design explicitly wanted this as
"queryable... context" for other agents, and nothing was actually reading
it. Rather than deleting it as dead weight, it's now formatted
(`schema.format_heading_info`) and included in the `test_pattern_gen` and
`generate` prompts, so the LLM actually gets the context it was collected for.

**Duplication removed**: `workbook_store.py`'s six input-sheet loaders each
repeated the same `find sheet → read matrix → find header row` sequence.
Factored into one `_load_sheet()` helper (see its docstring for the one
intentional behavior change this introduced: header-row detection now
consistently falls back to row 0 on a low-confidence match for every sheet,
rather than only some of them silently producing zero rows).

**Considered and deliberately left alone**: `app_param_extract.py` and
`io_signal_extract.py` follow a near-identical pattern to each other. They
were *not* merged into one generic function, unlike the sheet-loading
duplication above - each is short, and the codebase's stated principle is
one file per pipeline stage for traceability (a log line naming the stage
tells you exactly which file to open). Collapsing them would save a few
lines at the cost of that direct mapping.

**Not addressed**: many files mix `Optional[X]` (older `typing` style) with
`X | None` (current style, and already used elsewhere in this codebase) for
the same thing. Every file already has `from __future__ import annotations`,
so switching is safe, but it's purely cosmetic across ~80 occurrences
concentrated in `schema.py` - lower value than the fixes above for the
effort/review-risk, so left as-is rather than done as a blind bulk edit.
