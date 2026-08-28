"""Human-supplied, feature-specific factor tables for Test Pattern generation.

These are domain knowledge that cannot be derived from the input workbooks
(see plan Fix 3/5) - a feature with no entry here fails fast rather than
letting an LLM invent a plausible-looking factor table. More features will be
added here over time as the user supplies them; this module is the single
place that happens.

`signal_ref` on a Factor is the exact Model_Input_Mapping `Signal` this
factor sets, when known in advance (a safe, deterministic shortcut for
model_mapping_resolve). When omitted, model_mapping_resolve falls back to an
LLM-driven lookup against the feature's valid signal list, subject to the
same hallucination check as everything else.
"""
from __future__ import annotations

from .schema import Factor, FactorTable


class MissingFactorTableError(RuntimeError):
    """Raised when generate() is asked to process a feature with no
    registered factor table - fails fast rather than letting an LLM invent
    domain knowledge that is explicitly human/expert-owned."""


def _slope_assist_fixed_factors() -> list[Factor]:
    return [
        Factor(name="Truck Size", values=["1t", "3t"], ease_of_adjustment="Reset Required"),
        Factor(name="Discharge Capacity", values=["25% Discharge"], ease_of_adjustment="Easy"),
        Factor(
            name="Power Control Mode",
            values=["P", "S", "E"],
            ease_of_adjustment="Easy",
            signal_ref="CAN_HIL_PwrCtrlMode",
        ),
        Factor(
            name="Direction Switch",
            values=["FWD", "BWD"],
            ease_of_adjustment="Easy",
            signal_ref="MDL_SWH_DIR_STATE",
        ),
        Factor(name="Load Capacity", values=["NL", "FL"], ease_of_adjustment="Easy", signal_ref="MDL_SEN_Load"),
    ]


def _slope_assist_variable_factors() -> list[Factor]:
    return [
        Factor(name="Option Set", values=["Disabled", "Enabled"], ease_of_adjustment="Moderately Difficult"),
        Factor(
            name="Slope angle",
            values=["0 deg", "3 deg"],
            ease_of_adjustment="Easy",
            signal_ref="MDL_SEN_Slope_Angle",
        ),
    ]


def _slope_assist_table(feature_id: str) -> FactorTable:
    return FactorTable(
        feature_id=feature_id,
        fixed_factors=_slope_assist_fixed_factors(),
        variable_factors=_slope_assist_variable_factors(),
    )


# Slope Assist's factor table, registered under both feature ids seen for it:
# "002" (the test spec *document's* own numbering, TE_TMHC_Test_Spec_002_Slope_Assist)
# and "019" (the actual System-Requirements Index-sheet feature id - the Master
# Input Output Signals sheet shows Accelerator_Sensor/Tire_Angle_Sensor/
# Power_Select/Slope_Sensor all marked 'O' only under column 019, confirming
# 019 is Slope Assist's real feature id there). Same factor content, two keys.
_FACTOR_TABLES: dict[str, FactorTable] = {
    "002": _slope_assist_table("002"),
    "019": _slope_assist_table("019"),
}


def get_factor_table(feature_id: str) -> FactorTable:
    table = _FACTOR_TABLES.get(feature_id)
    if table is None:
        raise MissingFactorTableError(
            f"No factor table registered for feature {feature_id!r}. Factor tables are human-supplied "
            f"domain knowledge (see factors.py) - add one before generating test cases for this feature."
        )
    return table


def register_factor_table(table: FactorTable) -> None:
    """Register (or overwrite) a feature's factor table at runtime."""
    _FACTOR_TABLES[table.feature_id] = table
