from __future__ import annotations

import pytest

from .fixtures.build_fixtures import FEATURE_ID, build_all


@pytest.fixture()
def fixture_paths(tmp_path) -> dict[str, str]:
    return build_all(str(tmp_path))


@pytest.fixture()
def feature_id() -> str:
    return FEATURE_ID
