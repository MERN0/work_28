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
        │  2. get_llm()                         ── llm.py
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
cli.py                    Argument-based CLI wrapper around sys5.generate() for a real
                         run against real files from a terminal - point it at your 5
                         input workbooks + a feature id + an output dir (§8b).
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
agents.py                 One function, call_llm() - every LLM-backed node calls it
                         to make a single-shot structured-output request. No
                         tool-calling agent, no multi-turn loop - see its module
                         docstring for why (§7 covers the failure mode this avoids).
prompts.py                Every prompt template, in one dict, keyed by stage name.

state.py                  The two TypedDicts (PipelineState, TestCaseState) threaded
                         through the outer and inner LangGraph graphs, plus
                         valid_signal_names() - a small shared helper both
                         model_mapping_resolve and graph.py's context builder use.
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

`compound_command_map` relies on **lexical** keyword-overlap search
(`rapidfuzz.fuzz.token_set_ratio` in `workbook_store.py`'s
`search_compound_commands`/`search_library`) to narrow ~700 compound
commands / ~50 libraries down to a shortlist (`pipeline_config.
compound_command_shortlist_size`/`library_shortlist_size`, 30 each) that's
embedded directly in the one prompt the LLM sees for that requirement. This
is keyword overlap, not semantic similarity — if a requirement's wording
shares no vocabulary with the right command's name/steps, that command may
never make the shortlist, and (since this is a single-shot call — see §9's
most recent entry) the LLM can't re-search with a different term the way an
earlier tool-calling version of this stage could. There is currently no
embedding/semantic fallback; the shortlist size was raised specifically to
compensate for losing that re-search capability. Everything downstream of a
*selected* name is still hallucination-checked (§5) — so a wrong-but-real
command can pass that check; only the fidelity/plausibility validation might
catch it being the wrong choice for the requirement, and only if it happens
to notice. If this proves insufficient in practice, the fix is a bigger
shortlist or a second deterministic Python-side query with different terms -
not reintroducing agentic tool exploration (see agents.py's module
docstring for why that was removed).

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
wiring (`test_graph_build.py`), `call_llm()`'s retry-on-validation-error loop
with a stubbed chat model (`test_agents.py`), the concurrent test-case loop's
ordering/crash-safety with a stub subgraph (`test_test_case_loop.py`), and
`pipeline_config.py`'s load/override chain (`test_pipeline_config.py`). A
real end-to-end run (real Excel files, real LLM) can only be exercised in
the deployed environment.

## 8b. Running against real input files from the CLI

`cli.py` is a thin argparse wrapper around the exact same `sys5.generate(config)`
entry point the production harness calls - a manual CLI run and a harness run
execute identical pipeline code, no stubbing. It needs real network access to
whatever LLM endpoint `pipeline_config.json` (or its env var overrides) points
at, since it makes real LLM calls.

Point it at your 5 input workbooks individually:

```bash
cd backend
python app/core/artifacts/system/sys5/cli.py \
    --requirements       "/path/to/System Requirements.xlsx" \
    --command-list       "/path/to/TE_TMHC_Command_List.xlsx" \
    --configuration      "/path/to/TE_TMHC_Configuration_File.xlsx" \
    --compound-commands  "/path/to/TE_TMHC_Compound_Commands.xlsx" \
    --keyword-library    "/path/to/TE_TMHC_..._Keyword_Library_Description_Sheet.xlsx" \
    --feature-id 019 \
    --output-dir /path/to/output
```

...or, if all 5 already sit in one folder under their usual names, point
`--input-dir` at it instead and skip the individual flags - they resolve by
fuzzy name match, exactly like the production harness's `input_folder_path`
does (see `workbook_store.resolve_input_files`):

```bash
python app/core/artifacts/system/sys5/cli.py \
    --input-dir /path/to/input_folder \
    --feature-id 019 \
    --output-dir /path/to/output
```

`--feature-id` is the System Requirements workbook's sheet name for the
feature to generate test cases for - it must already have a factor table
registered in `factors.py`, or the run fails fast with
`MissingFactorTableError` before any LLM work starts. Run
`python app/core/artifacts/system/sys5/cli.py --help` for every flag
(`--model` to override the LLM model, `--project-name`, etc.). Also runnable
as `python -m app.core.artifacts.system.sys5.cli ...` from `backend/` - see
`cli.py`'s own docstring for the PEP 366 detail that makes both work.

## 9. Codebase audit notes (deprecated APIs, dead code, simplifications)

From a pass that checked every LangChain/LangGraph API call against current
documentation (via the `docs-langchain`/`reference-langchain` MCP tools, not
memory) and grepped for unused code:

**Superseded entirely: the tool-calling agent layer.** Earlier versions of
this codebase built a `langchain.agents.create_agent(...)` tool-calling loop
per LLM-backed stage (with `langgraph.prebuilt.create_react_agent` as a
deprecated fallback if `create_agent` wasn't importable), giving the LLM
read-only tools (`tools.py`, `StructuredTool.from_function`-wrapped
`InMemoryWorkbookStore` methods) it could call mid-conversation. Against the
real deployment (a litellm proxy in front of a self-hosted `gpt-oss-120b`
via vLLM), that repeatedly broke in the specific place a tool-calling loop
is exposed: the *second* turn, once a completed tool call was already in the
conversation history (see entry 2 below - the `output_version="v0"` fix was
a real but partial workaround for this, not the actual fix). Replaced with a
single-shot architecture: every stage's Python code already knows how to
fetch/shortlist whatever context its LLM call needs (that logic lives in
`workbook_store.py` and didn't change), so every node now assembles that
context into the prompt itself and makes exactly ONE
`llm.with_structured_output(schema)` call via `agents.py`'s `call_llm()` -
never a second turn, never a `ToolMessage`, which is what makes this immune
to the whole bug class rather than one more patch for it. `tools.py` is
deleted; every node's `build(store, llm, tools, pipeline_config)` lost the
`tools` parameter; the top-level `langchain` package (only used for
`create_agent`) is no longer a dependency at all. See `agents.py`'s module
docstring for the full reasoning, and §7 for the one real trade-off (the LLM
can no longer autonomously re-search a missed shortlist).

**Outdated (not deprecated, but superseded) parameter names fixed**:
`llm.py` was constructing `ChatOpenAI(openai_api_key=..., openai_api_base=...,
request_timeout=...)` - old aliases that still work today via Pydantic
backwards-compatibility, but the current documented constructor parameters
are `api_key`, `base_url`, and `timeout`
(https://reference.langchain.com/python/langchain-openai/langchain_openai/chat_models/base/ChatOpenAI).
Updated to match.

**Confirmed NOT deprecated** (checked because they looked like candidates):
Pydantic v2 usage throughout (`model_dump`/`model_validate`/`model_copy`, no
`.dict()`/`.json()`/v1 shims) - already current.
`llm.with_structured_output(schema)` (`langchain_core.language_models.BaseChatModel`)
- the documented single-call mechanism for a typed answer from any chat
model, current as of this codebase's pinned `langchain-core` version.

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

**Two real correctness bugs found and fixed after this audit, via an actual
dry run of the pipeline (not just static review)**:

1. **Library-call hallucination-guardrail false-negative.** `store.exists()`'s
   `"library_call"` branch and `compound_command_map.py` both derived a
   library function's bare name from its Library-List signature by splitting
   on `"("` - which, for the real signature style
   `"Lib_Ramp Signal_Name(Start=X,...)"` (no space before the parameter
   list), kept the literal placeholder parameter name and yielded
   `"Lib_Ramp Signal_Name"` instead of `"Lib_Ramp"`. A real generated step
   referencing `"Lib_Ramp"` then scored only ~57 on `token_sort_ratio`
   against that candidate - far below the 90-92 thresholds used throughout -
   so **every** step calling a library function would fail the hallucination
   check. Fixed with `excel_io.leading_identifier()`, which splits on
   whitespace *before* looking for `"("`, resolving correctly for both that
   style and the space-before-parens style (`"Lib_CheckTorqueLimit (...)"`).
   Also gave `TestStep.target_ref` an explicit `Field` description so the LLM
   knows to put the bare name there, not the full call with arguments.

2. **litellm 400 on the gpt-oss-120b endpoint mid-run** (`... 1 validation
   error for Message\ncontent.0\n  Input should be a valid dictionary or
   instance of Content [...ValidatorIterator...]`), reported against a real
   run once an agent's conversation history included a completed tool call.
   Traced (by reading the installed `langchain_openai` source directly,
   since `reference.langchain.com`/`docs.langchain.com` are unreachable from
   this sandbox) to `langchain-openai>=1.0`'s default `AIMessage` output
   format change (`output_version="responses/v1"`, a list of typed content
   blocks, replacing the pre-1.0 plain-string `content`) - not reliably
   compatible with every OpenAI-*compatible* self-hosted backend, and this
   endpoint is exactly that: an internal litellm proxy in front of a
   self-hosted `gpt-oss-120b` via vLLM, not real OpenAI. Matches a known,
   already-filed LangChain issue against this same model family
   (https://github.com/langchain-ai/langchain/issues/34751). Fixed at the
   time in `llm.py`'s `get_llm()`: `output_version="v0"` (the officially
   documented backwards-compatibility value - plain-string content again)
   and `use_responses_api=False`. That setting is still in place (harmless,
   still the right default for this endpoint), but it turned out to be a
   partial workaround, not the real fix - further "llm validation error"
   reports kept surfacing from the same root cause (a tool-calling agent's
   multi-turn conversation history). The actual fix was architectural: see
   the "Superseded entirely: the tool-calling agent layer" entry above -
   removing tool-calling agents altogether (single-shot `call_llm()` calls,
   no second turn, ever) closes off this whole bug class rather than
   patching around one symptom of it.

3. **Functional/NonFunctional Requirement category collision.** The
   Requirement-sheet Category fast-path (`requirements_extract.py`) fuzzy-
   matches a row's raw Category text against the known vocabulary at
   `category_match_threshold` (was 85). `rapidfuzz.token_sort_ratio` scores
   `"Non Functional Requirement"` (space- or underscore-separated - not an
   exact match to the vocabulary entry `"NonFunctional Requirement"`)
   against `"Functional Requirement"` at ~91.7 - above that old threshold,
   so a non-functional requirement row would silently fast-path as
   Functional and get real test cases generated for it, never reaching the
   LLM escalation path Decision 6 relies on for exactly this kind of
   ambiguity. Raised `category_match_threshold` to 95 (comfortably above the
   ~91.7-93.6 collision range, still below genuine-typo scores of 97.7-100 -
   see the threshold's own comment in `pipeline_config.py`), and added
   `tests/test_requirements_extract.py` as a direct regression test:
   `Category == "Functional Requirement"` is the *only* value that ever
   produces a testable `Requirement` - every other known category
   (`NonFunctional Requirement`, `Configuration Requirement`,
   `Security Requirement`), even a clean non-ambiguous match, is recognized
   and then dropped, never appearing in `requirements` *or* `heading_info`.

4. **Pydantic `ValidationError` on a numeric master-sheet cell**, reported
   against a real input file (`AppParameter.valid_value: Input should be a
   valid string (type=string_type, input_value=300, input_type=int)`).
   `comm_matrix_extract.py`, `app_param_extract.py`, and `io_signal_extract.py`
   passed raw `row.get(...)` cell values straight into `CommMatrixSignal`/
   `AppParameter`/`IOSignal`, all typed as plain `str` fields - openpyxl reads
   a numeric-looking cell (e.g. a parameter's valid/default value) as a real
   Python `int`/`float`, and pydantic v2 does not coerce non-`str` input into
   a `str` field. Every other loader in this codebase (`workbook_store.py`'s
   own `_load_*` methods, `requirements_extract.py`) already wraps raw cell
   values in `excel_io._norm()` first; these three were the only ones that
   didn't, because the synthetic test fixtures write every cell as an
   already-quoted string literal and never exercised a genuinely numeric
   one. Fixed with a local `_s()` helper in each of the three files, plus
   `tests/test_master_sheet_extract_nodes.py`, which feeds literal Python
   `int`/`float` values (mirroring real openpyxl output) through each node
   directly to reproduce the exact reported crash.

5. **`test_pattern_gen` never completing** (reported as "takes a long long
   time even for a single requirement… execution has never moved forward
   past this part", after an earlier report of request timeouts on the same
   stage). Not a prompt-size or model-speed problem: `ChatOpenAI`'s
   `with_structured_output` defaults to `method="json_schema"`, which sends
   the pydantic schema as a strict `response_format` - and a self-hosted
   backend (this deployment's vLLM behind litellm) compiles that schema into
   a **grammar for guided decoding**. `_ScenarioPlan` had two `dict[...]`
   fields, which pydantic renders as `{"type": "object",
   "additionalProperties": {...}}` with no fixed `properties` - objects with
   *arbitrary* keys, i.e. an effectively unbounded grammar. Dumping every
   structured-output schema in the pipeline and counting
   `additionalProperties` gave an exact fingerprint: `test_pattern_gen` was
   the **only** schema with open-ended maps, and the only stage that never
   completed - every other stage's schema is fully closed and every other
   stage ran fine. Fixed by closing the schema: `variable_transitions` and
   `excluded_fixed_factor_values` are now lists of fixed-key objects
   (`_FactorTransition`, `_ExcludedValues`) that `_expand` converts back to
   dicts internally, so the wire schema is bounded and the stored
   `TestPatternRow` shape is unchanged. **Keep every structured-output
   schema in this codebase closed** - no bare `dict`/`Any`-keyed fields -
   or this comes straight back.

   Two opt-in levers were added alongside it, both default-off so nothing
   changes silently: `pipeline_config.structured_output_method` (switch to
   `"function_calling"` if a backend build handles `json_schema` badly) and
   `pipeline_config.llm_reasoning_effort` (send OpenAI's `reasoning_effort`
   - `"low"` trades planning depth for a large wall-clock win on a reasoning
   model like gpt-oss). `call_llm()` also now logs each call's wall-clock at
   INFO, so `sys5_run.log` shows exactly which call is slow.

6. **Near-total hallucination rate on `SDO_Set`/`SDO_Verify` steps** (~9 of
   10 steps flagged by `hallucination_check`, every one a `ref_kind="command"`
   miss), reported against a real run. Root cause:
   `comm_matrix_extract.py`'s `CommMatrixSignal.command_name` is only
   populated when a signal's Command List fuzzy match scores
   `>= command_match_threshold` (80) - a deterministic fast-path for other
   callers - but `generate`'s prompt only ever showed *that* gated value via
   `state.valid_signal_names()`. Any signal whose true match scored just
   under 80 (or whose real-world naming simply didn't score that cleanly)
   had its real Command List name hidden from the LLM entirely - it then had
   to guess a plausible `CAN_HIL_<Name>`/`CAN_Main_<Name>` name from the
   *pattern* the prompt itself demonstrates, and an invented name essentially
   never matches a real Command List entry. Fixed with
   `graph.py::_build_signal_reference()`: for every feature-valid signal,
   recompute `store.lookup_command_name(..., top_k=3)` fresh (cheap - a
   local rapidfuzz call, not an LLM cost) and show the real candidates
   unconditionally, letting the LLM make the actual judgment call itself -
   the same shortlist-then-LLM-picks pattern `compound_command_map` already
   used. Replaces the old flat `context["valid_signals"]` list with
   `context["signal_reference"]` in both `generate.py` and `correct.py`;
   `prompts.py`'s `generate` prompt was also tightened to say explicitly
   that a Command List name must be copied verbatim from a given candidate,
   never derived from the naming pattern alone, and that a `Compound <name>`
   step is atomic (never re-emit its internal steps as separate steps -
   a second, smaller contributing risk to the same failure mode). See
   `tests/test_context_builder.py` for a direct regression test (asserts a
   signal with `command_name=None` - the exact below-threshold case - still
   surfaces its real candidates).

7. **A second, distinct cause of the same symptom** (found from a real run's
   log showing failures explicitly logged as `ref_kind="signal"` for real
   `CAN_Main_*` names - a name that exists, rejected anyway):
   `TestStep.ref_kind` was a field the LLM filled in independently of
   `TestStep.keyword`, so the two could disagree - a step correctly keyworded
   `SDO_Set` could still carry `ref_kind="signal"`, sending
   `hallucination_check` to check a real Command List name against the
   *signal* candidate pool (Comm Matrix/IO Signal/Model Input Mapping names),
   which it was never going to find. There is no legitimate case where the
   same keyword needs two different ref_kinds, so this was never something
   worth asking the model - fixed by deriving it deterministically instead:
   `schema.derive_ref_kind(keyword)` (a plain dict lookup) is now applied to
   every step in `generate.py` and `correct.py` immediately after the LLM
   call, **overwriting** whatever `ref_kind` the model produced. The model
   still emits a `ref_kind` field (required by the closed structured-output
   schema - see finding 5 above on why every schema here stays closed) but
   it is unconditionally discarded.

   As defense in depth for the *other* direction of the same confusion (the
   model picks a real name but the "wrong" keyword for it - e.g. `Set`
   instead of `SDO_Set` for a genuinely CAN-sourced signal, a plausibility
   mistake `validate_pass2` is better suited to catch than the existence
   guardrail), `store.exists()` now checks `ref_kind="signal"` against the
   Command List too, and `ref_kind="command"` against the signal pool too,
   before failing either. A name that's real under the "other side" of the
   distinction still passes; a genuinely invented name still fails both.

   Separately, `workbook_store.get_feature_marked_rows()` now logs (at
   WARNING) whenever a sheet resolves zero rows to a clean `O` for a feature
   - the resolved column index/header plus the most common raw marker cell
   values actually seen, e.g. distinguishing "wrong column matched" from "the
   real file doesn't use a plain ASCII O" (a lookalike Unicode character, a
   checkmark, a formula result) from "genuinely every row is ambiguous for
   this feature". Not a fix by itself - a diagnostic for whichever of those
   turns out to be true, added because a real run showed 0 valid via the
   fast-path on every master sheet simultaneously, which is itself worth
   confirming rather than assuming.

   See `tests/test_ref_kind_normalization.py` and
   `tests/test_workbook_store.py::test_hallucination_guardrail_exists_falls_back_across_signal_and_command`.

8. **User-directed scope/performance tightening**, requested together after
   the hallucination fixes above: generated test cases were taking too long
   ("infinitely long... even for 1 req") and were paraphrasing exact
   short-form values instead of copying them.

   - **`max_test_cases_per_requirement` cap (default 5).** The combinatorial
     sweep in `test_pattern_gen.py` (`_expand`) can legitimately produce more
     rows than are worth the wall-clock cost - each row costs at least one
     `generate` + one `validate` LLM call, more on a correction. New
     `_cap_rows()` enforces the cap *after* expansion, round-robining across
     scenarios first (so a cap smaller than the scenario count still keeps at
     least one row per scenario instead of only ever keeping the first
     scenario's rows) and renumbering `test_case_no` sequentially afterward
     so kept rows stay a gapless `1..N`. Logged at INFO whenever it actually
     truncates.
   - **`llm_reasoning_effort` default changed from `None` to `"low"`.** Every
     stage in this pipeline only ever asks for a small, already-scoped answer
     (never open-ended reasoning), so a reasoning model's higher-effort
     analysis budget was pure wall-clock cost with no answer-quality benefit
     here - see the field's comment in `pipeline_config.py`.
   - **Slope Assist's `Load Capacity` factor trimmed to `["NL"]`** (was
     `["NL", "FL"]`) in `factors.py` - user-directed: only No Load needs
     sweeping for this feature; Full Load was roughly doubling its row count
     for no requested benefit. `Power Control Mode` (`["P", "S", "E"]`) is
     unchanged - all power modes still need coverage.
   - **Exact-value + units prompt strengthening.** Generated steps were
     paraphrasing factor values instead of copying them verbatim (e.g.
     writing "Forward" for `FWD`, "Power mode" for `P`, "No Load" for `NL`) -
     wrong, since these short forms are the actual values the test rig
     expects. Added an explicit paragraph to the `generate` prompt requiring
     verbatim copying from the fixed/variable factor context and from
     resolved factor signal mappings, plus a requirement to fill in a step's
     Units (and a Verify's Units2) from the matching tolerance whenever one
     exists, rather than leaving it blank. Mirrored both requirements as new
     Rubric 2 checklist bullets in both `validate_pass2` and
     `validate_combined`, so a paraphrased value or a missing unit now fails
     validation and triggers the one-shot correction pass instead of
     reaching the output workbook silently.

   Verified via the full test suite (68 passed) and a fresh dry-run: the
   fixture requirement's 12-row combinatorial expansion
   (`Truck Size(2) x Power Control Mode(3) x Direction Switch(2) x Load
   Capacity(1)`) now caps to 5 test cases as configured, 0 flagged.

9. **`SDO_Set`/`SDO_Verify` deprecated - folded into plain `Set`/`Verify`**
   (user-directed: the underlying keyword library no longer distinguishes a
   CAN/SDO-sourced signal from a model-input one at the step-keyword level).
   Removed both from `StepKeyword` in `schema.py`; `Set`/`Verify` now cover
   every signal, model-input or CAN/SDO-sourced, and both still derive
   `ref_kind="signal"` via `derive_ref_kind` (see finding 7 above) -
   `store.exists()`'s signal branch already cross-checks the Command List as
   well as the signal pool (also finding 7), so a real CAN_HIL_*/CAN_Main_*
   name written under plain `Set`/`Verify` still validates correctly; no
   change needed there. Updated the `generate` prompt's step vocabulary and
   both validation rubrics to describe Set/Verify as covering both signal
   sources and to call out SDO_Set/SDO_Verify as deprecated (so a model that
   still reaches for the old keywords out of prior habit gets flagged and
   corrected rather than silently passing). `tests/test_ref_kind_normalization.py`'s
   mismatched-ref_kind regression case was re-targeted at `Compound` (the
   `SDO_Set` example it used no longer type-checks against `StepKeyword`);
   the dry-run driver's scripted stub was updated the same way and re-verified
   end to end (5 test cases, 0 flagged, using `Set` for the CAN-sourced
   `CAN_HIL_PwrCtrlMode`/`CAN_Main_Slope_Assist_Enabled_Disabled` steps).
