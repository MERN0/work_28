"""Pydantic data contracts shared across the SYS5 pipeline.

These models are the boundary between "raw cells read off a workbook" and
"structured data an LLM agent reasons over / a tool returns". Nothing here
enforces business-vocabulary correctness (e.g. Priority isn't an enum) because
source sheets are known to carry typos/whitespace variance (see excel_io.py's
fuzzy matching) - only structural shape is enforced.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

TestPhase = Literal["PRECONDITION", "ACTION", "POSTCONDITION"]

# What kind of real-world thing a TestStep's target_ref must resolve to in the
# InMemoryWorkbookStore. Used by the hallucination guardrail.
RefKind = Literal[
    "signal",           # a Comm Matrix / IO Signal / Model Input Mapping signal name
    "command",           # a Command List "Command name"
    "compound_command",  # a "Compound <name>" block from the Compound Commands workbook
    "tolerance",         # a Tolerances sheet "Tolerance Configuration" name (Config_Tol_*)
    "library_call",       # a Library List entry (Lib_*)
    "parameter",          # an App Parameter name
    "none",                # step needs no existence check (e.g. bare `Wait`)
]

StepKeyword = Literal[
    "Test_start", "End_of_test",
    "Set", "SDO_Set", "Verify", "SDO_Verify", "Wait", "Wait_Until",
    "Read", "ReadStore", "Compound", "Config_Tol", "FIU", "Lib",
]


# --------------------------------------------------------------------------
# Requirements sheet
# --------------------------------------------------------------------------

class Requirement(BaseModel):
    req_id: str
    description: str
    category: str
    variant: Optional[str] = None
    priority: Optional[str] = None
    verification_method: Optional[str] = None
    verification_criteria: Optional[str] = None
    verification_stage: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    release: Optional[str] = None
    downstream_traceability: Optional[str] = None
    remarks: Optional[str] = None


class HeadingInfoRow(BaseModel):
    """A Heading/Information-category row from a requirement sheet, kept as
    queryable context (not turned into a test case)."""
    req_id: Optional[str] = None
    description: str
    category: str


class AbbreviationEntry(BaseModel):
    abbreviation: str
    definition: str


# --------------------------------------------------------------------------
# Master sheets (Comm Matrix / App Parameter / IO Signals) - valid rows only
# --------------------------------------------------------------------------

class CommMatrixSignal(BaseModel):
    signal_id: Optional[str] = None
    message_name: Optional[str] = None
    message_ids: Optional[str] = None
    logical_signal_name: Optional[str] = None
    signal_name: Optional[str] = None
    signal_description: Optional[str] = None
    command_name: Optional[str] = None  # resolved via Command List lookup, not read directly


class AppParameter(BaseModel):
    parameter_id: Optional[str] = None
    parameter_name: Optional[str] = None
    parameter_description: Optional[str] = None
    parameter_type: Optional[str] = None
    unit: Optional[str] = None
    valid_value: Optional[str] = None
    default_value: Optional[str] = None
    min_value: Optional[str] = None
    max_value: Optional[str] = None
    resolution: Optional[str] = None


class IOSignal(BaseModel):
    signal_id: Optional[str] = None
    logical_signal_name: Optional[str] = None
    signal_type: Optional[str] = None
    variants: Optional[str] = None
    ecu: Optional[str] = None
    input_output: Optional[str] = None


# --------------------------------------------------------------------------
# Command List / Tolerances / Model Input Mapping
# --------------------------------------------------------------------------

class CommandListEntry(BaseModel):
    type: Optional[str] = None
    command_name: str
    message_name: Optional[str] = None
    signal_description: Optional[str] = None
    signal_name: Optional[str] = None


class ToleranceEntry(BaseModel):
    tolerance_configuration: str  # e.g. "Config_Tol_Spd"
    description: Optional[str] = None
    unit: Optional[str] = None
    value_positive: Optional[str] = None
    value_negative: Optional[str] = None
    tolerance_unit: Optional[str] = None
    remarks: Optional[str] = None


class ModelInputMappingRow(BaseModel):
    signal: str
    test_case_input: Optional[str] = None
    model_input: Optional[str] = None
    model_output_to_ecu: Optional[str] = None
    remark: Optional[str] = None


# --------------------------------------------------------------------------
# Compound Commands / Library / Custom Keywords
# --------------------------------------------------------------------------

class CompoundCommandStep(BaseModel):
    keyword_line: str  # e.g. "Verify MDL_PS_B48V" - raw step text within the block
    parameter_settings: Optional[str] = None
    units: Optional[str] = None
    expected_value: Optional[str] = None
    units2: Optional[str] = None
    whether_execute: Optional[str] = None
    remarks: Optional[str] = None


class CompoundCommand(BaseModel):
    name: str
    source_sheet: Literal["Set", "Verify"]
    steps: list[CompoundCommandStep] = Field(default_factory=list)


class LibraryEntry(BaseModel):
    signature: str  # e.g. "Lib_Ramp Signal_Name(Start=X,Stop=X,Step=X,Time=X)"
    description: Optional[str] = None
    example_usage: Optional[str] = None


class CustomKeywordEntry(BaseModel):
    format: str
    type: Optional[str] = None
    logical_formula: Optional[str] = None
    example: Optional[str] = None


# --------------------------------------------------------------------------
# Factors (human-supplied domain knowledge, see factors.py)
# --------------------------------------------------------------------------

class Factor(BaseModel):
    name: str
    values: list[str]
    ease_of_adjustment: Optional[str] = None
    signal_ref: Optional[str] = None  # explicit Model_Input_Mapping "Signal" this factor sets, if known


class FactorTable(BaseModel):
    feature_id: str
    fixed_factors: list[Factor]
    variable_factors: list[Factor]


# --------------------------------------------------------------------------
# Test Pattern
# --------------------------------------------------------------------------

class TestPatternRow(BaseModel):
    test_case_no: int
    scenario_id: str
    fixed_values: dict[str, str]     # factor name -> value, for this row
    variable_transitions: dict[str, str]  # factor name -> "A -> B" transition text


# --------------------------------------------------------------------------
# Test Case / Test Step
# --------------------------------------------------------------------------

class TestStep(BaseModel):
    step_no: int
    phase: TestPhase
    keyword: StepKeyword
    target_ref: Optional[str] = None       # signal/command/compound/tolerance/library name referenced
    ref_kind: RefKind = "none"
    step_text: str                          # full literal step text as it should appear in the sheet
    parameter_settings: Optional[str] = None
    units: Optional[str] = None
    expected_value: Optional[str] = None
    units2: Optional[str] = None
    whether_execute: str = "Yes"
    remarks: Optional[str] = None


class TestCase(BaseModel):
    test_case_id: str
    feature: str
    variant: Optional[str] = None
    requirement_ids: list[str]
    priority: Optional[str] = None
    mode_of_execution: str = "Automated"
    description: str
    steps: list[TestStep]
    status: Literal["clean", "flagged"] = "clean"
    flag_reason: Optional[str] = None
    remarks_summary: Optional[str] = None  # compact factor summary for Item List


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    message: str
    step_no: Optional[int] = None


class ValidationResult(BaseModel):
    rubric: str
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


class CombinedValidationResult(BaseModel):
    """Both validation rubrics answered in one LLM call (see
    pipeline_config.combine_validation_passes / nodes/validate.py::build_combined) -
    still two distinct ValidationResult objects, just produced together."""
    fidelity: ValidationResult
    plausibility: ValidationResult


# --------------------------------------------------------------------------
# Run manifest
# --------------------------------------------------------------------------

class ProducedManifest(BaseModel):
    output_files: list[str] = Field(default_factory=list)
    feature_id: str = ""
    feature_name: str = ""
    requirement_count: int = 0
    test_case_count: int = 0
    flagged_count: int = 0
    started_at: str = ""
    finished_at: str = ""
