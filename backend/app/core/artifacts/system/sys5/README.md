# SYS5 — Test Pattern Extractor

Reads a System Requirements workbook and, for one feature (a sheet in that
workbook) at a time, extracts every Functional Requirement and generates its
Test Pattern (the combinatorial set of scenarios/factor-value rows a real
test case would later be built from). The result is written as a single JSON
file. Everything lives in this one directory
(`backend/app/core/artifacts/system/sys5/`) — no shared code outside it.

This is a deliberately narrow scope: extraction and Test Pattern generation
only, nothing about writing actual test-case steps, validating them, or
producing an Excel workbook.

## 1. What happens when you call `generate(config)`

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
        │  1. load_inputs()                    ── nodes/load_inputs.py
        │       resolve_requirements_file()      + InMemoryWorkbookStore.load()  ── workbook_store.py
        │       (the requirements workbook is parsed from disk ONCE, here)
        │
        │  2. get_llm()                         ── llm.py
        │
        │  3. a 3-node StateGraph runs, in order:
        │       feature_index → requirements_extract → test_pattern_gen
        ▼
  sys5.py: generate() resumes
        │  writes one JSON file: every extracted requirement, each with its
        │  own list of Test Pattern rows (nodes/test_pattern_gen.py's output)
        ▼
  returns the JSON file's path
```

## 2. The two config surfaces — don't confuse them

| | `config` dict (→ `config.py`'s `Settings`) | `pipeline_config.json` (→ `pipeline_config.py`'s `PipelineConfig`) |
|---|---|---|
| Who sets it | The calling harness, per run (`generate(config)`'s argument) | You, by hand-editing the JSON file |
| What it holds | *This run's* project name, file path, which feature/sheet to process | Every reusable engineering knob: LLM model/credentials/retries, fuzzy-match thresholds, logging |
| Where it's read | `Settings.from_config(config)` in `sys5.generate()` | `PipelineConfig.load()` in `sys5.generate()` |

If you want to change how *this specific request* is processed (which
feature, which file), that comes from the caller's `config` dict. If you want
to change how the pipeline *behaves* (stricter/looser matching, which model,
how many test-pattern rows per requirement), edit `pipeline_config.json`.

## 3. Module map

```
sys5.py                 entry point: generate(config) -> JSON file path. Also runnable
                         standalone (`python sys5.py config.json`) - see its docstring
                         for the PEP 366 trick that makes both modes work.
cli.py                    Argument-based CLI wrapper around sys5.generate() for a real
                         run against a real requirements workbook from a terminal.
config.py                Settings: the per-run config dict, typed.
pipeline_config.py/.json PipelineConfig: engineering knobs, one place to edit (§2).
logging_utils.py        configure_logging() / get_logger() / stage_timer() - every
                         node's log lines go through this.

excel_io.py              Judgment-free Excel primitives: read a sheet, find a header
                         row, fuzzy-match column names. Never decides what data
                         MEANS - only reads it honestly.
workbook_store.py        InMemoryWorkbookStore: parses the System Requirements
                         workbook once (via excel_io.py) into an in-memory store
                         the node layer queries instead of touching disk again.
factors.py                Human-supplied per-feature factor tables (Truck Size, Power
                         Control Mode, ...) - domain knowledge that can't be read out
                         of the Excel file. Fails fast (MissingFactorTableError) for
                         an unregistered feature rather than letting an LLM guess.

llm.py                   Builds the one ChatOpenAI client the run uses.
agents.py                 One function, call_llm() - the LLM-backed node calls it to
                         make a single-shot structured-output request.
prompts.py                The one prompt this pipeline uses (test_pattern_gen), kept
                         in a dict for the same reason the fuller pipeline did.

schema.py                  Pydantic models: Requirement, HeadingInfoRow, Factor/
                         FactorTable, TestPatternRow.
state.py                  PipelineState, the TypedDict threaded through the graph.
graph.py                   Builds and wires the StateGraph and run_pipeline(), the
                         top-level driver.

nodes/                     One module per pipeline stage - see §4.

tests/                     pytest suite + a synthetic fixture workbook. No real LLM
                         call anywhere in it (see tests/test_sys5.py, which stubs
                         call_llm for an end-to-end check).
```

## 4. The pipeline stages (`graph.py::_build_graph`)

Each stage is a LangGraph node — a plain function `PipelineState -> Partial[PipelineState]`
(https://docs.langchain.com/oss/python/langgraph/graph-api). They run in a
fixed linear order; `graph.py` wires the edges explicitly.

| Stage | File | Deterministic or LLM? |
|---|---|---|
| `feature_index` | `nodes/feature_index.py` | Deterministic - exact Index-sheet lookup |
| `requirements_extract` | `nodes/requirements_extract.py` | Deterministic - fuzzy match against the known `Category` vocabulary; anything that doesn't cross the threshold is dropped, never guessed |
| `test_pattern_gen` | `nodes/test_pattern_gen.py` | LLM plans scenarios; Python does the actual combinatorics (deterministic) |

Only `test_pattern_gen` calls the LLM, and only to plan which scenarios a
requirement's Verification Criteria describes and which factors each
exercises — the actual combinatorial expansion into rows is plain Python
(`_expand`), never a judgment call. This is the load-bearing design principle
in this codebase: **plain Python for finding what already exists or
computing a combinatorial product, an LLM only for the one genuinely
generative step (identifying testable scenarios from prose).**

## 5. Output shape

```json
{
  "feature_id": "019",
  "feature_name": "Slope Assist",
  "function_group": "Traction",
  "generated_at": "2026-01-01T12:00:00",
  "requirements": [
    {
      "req_id": "TMHC_SYSRS_FR019001",
      "description": "...",
      "category": "Functional Requirement",
      "variant": "...", "priority": "...", "...": "... (every Requirement field)",
      "test_patterns": [
        {"test_case_no": 1, "scenario_id": "...", "fixed_values": {...}, "variable_transitions": {...}},
        ...
      ]
    },
    ...
  ]
}
```

Every Functional Requirement extracted for the feature appears, each with its
own (possibly empty) `test_patterns` list, capped at
`pipeline_config.max_test_cases_per_requirement` rows per requirement.

## 6. Logging

Every stage above logs through `logging_utils.py`: `-> stage (context)` on
entry, `<- stage done in Xs` on success, or a full exception on failure.
Output goes to the console **and** to `<output_dir>/sys5_run.log`.

## 7. Running the tests

```bash
cd backend
pip install -r requirements.txt
python -m pytest app/core/artifacts/system/sys5/tests -q
```

No test in this suite reaches a real LLM/proxy - `tests/test_sys5.py` stubs
`call_llm` at its call site in `nodes/test_pattern_gen.py` and drives
`sys5.generate()` end to end against a synthetic fixture workbook. A real run
(real Excel file, real LLM) can only be exercised in the deployed environment
or via the CLI below.

## 8. Running against a real input file from the CLI

`cli.py` is a thin argparse wrapper around the exact same `sys5.generate(config)`
entry point the production harness calls. It needs real network access to
whatever LLM endpoint `pipeline_config.json` (or its env var overrides)
points at, since `test_pattern_gen` makes real LLM calls.

```bash
cd backend
python app/core/artifacts/system/sys5/cli.py \
    --requirements "/path/to/System Requirements.xlsx" \
    --feature-id 019 \
    --output-dir /path/to/output
```

...or, if the workbook lives in a folder by itself, point `--input-dir` at it
instead of `--requirements`.

`--feature-id` is the System Requirements workbook's sheet name for the
feature to extract test patterns for - it must already have a factor table
registered in `factors.py`, or the run fails fast with
`MissingFactorTableError` before any LLM work starts. Run
`python app/core/artifacts/system/sys5/cli.py --help` for every flag
(`--model` to override the LLM model, `--project-name`, etc.). Also runnable
as `python -m app.core.artifacts.system.sys5.cli ...` from `backend/` - see
`cli.py`'s own docstring for the PEP 366 detail that makes both work.

## 9. Scope history

This directory previously implemented a much larger pipeline: after
extracting Test Patterns, it went on to generate full test-case steps per
pattern row (an LLM-backed generate/hallucination-check/validate/correct
loop), resolve signal/compound-command references against four additional
reference workbooks, and write a multi-sheet Excel output workbook. That
machinery (`nodes/generate.py`, `hallucination_check.py`, `validate.py`,
`correct.py`, `finalize_pass.py`, `test_case_loop.py`,
`model_mapping_resolve.py`, `compound_command_map.py`,
`comm_matrix_extract.py`, `app_param_extract.py`, `io_signal_extract.py`,
`output_assemble.py`, `xlsx_writer.py`, and the corresponding
`RefKind`/`TestStep`/`TestCase`/`ValidationResult` schema and
`TestCaseState` inner graph) has been removed rather than carried forward
half-working: this codebase's current scope is Test Pattern extraction only,
saved as JSON, for every available requirement of one feature. Re-adding
test-case generation on top of this would be new work, not a restoration of
deleted code (the requirements/history live in this file's prior revisions
in version control, not as dead code in the tree).
