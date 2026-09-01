"""Builds a small synthetic System Requirements xlsx fixture matching the
real input schema. Used by pytest fixtures in conftest.py.
"""
from __future__ import annotations

import os

from openpyxl import Workbook

FEATURE_ID = "002"


def build_system_requirements(out_dir: str) -> str:
    wb = Workbook()
    wb.remove(wb.active)

    cover = wb.create_sheet("Cover Page")
    cover.append(["System Requirements - Test Fixture"])

    index = wb.create_sheet("Index")
    index.append(["Feature ID Link", "Feature Name", "Function Group"])
    index.append(["002", "Slope Assist", "Traction"])
    index.append(["005", "Other Feature", "Braking"])

    req = wb.create_sheet(FEATURE_ID)
    req.append(
        [
            "Requirement ID", "Requirement Description", "Category", "Variant", "Priority",
            "Verification Method", "Verification Criteria", "Verification Stage", "Source",
            "Status", "Release", "Downstream Traceability", "Remarks",
        ]
    )
    req.append(["", "Slope Assist Requirements", "Heading", "", "", "", "", "", "", "", "", "", ""])
    req.append(
        [
            "TMHC_SYSRS_FR002001",
            "The system shall enable slope assist when the slope angle exceeds the threshold while moving forward.",
            "Functional Requirement", "Variant 1", "P1",
            "Testing", "Verify slope assist enables when slope angle transitions from 0 deg to 3 deg while moving forward in E mode.",
            "System Testing", "CustReq-1", "Approved", "R1", "", "",
        ]
    )
    req.append(
        [
            "TMHC_SYSRS_FR002002",
            "The system shall disable slope assist when the option set is disabled.",
            "Funtional Requiremnt",  # typo'd category - deliberately NOT a clean fuzzy match against the known vocabulary
            "Variant 1", "P2", "Testing", "Verify slope assist disables when Option Set is Disabled.",
            "System Testing", "CustReq-2", "Approved", "R1", "", "",
        ]
    )

    path = os.path.join(out_dir, "System Requirements.xlsx")
    wb.save(path)
    return path


def build_all(out_dir: str) -> dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    return {"requirements": build_system_requirements(out_dir)}
