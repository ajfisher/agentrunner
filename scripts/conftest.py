from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    state = tmp_path / 'state'
    state.mkdir(parents=True, exist_ok=True)
    return state
