# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent real-QTest regression checks for the minimal-layout iteration."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "verify_minimal_ui", ROOT / "tools/verify-minimal-ui.py"
)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


@pytest.mark.parametrize("scenario", list(ui.SCENARIOS))
def test_minimal_native_ui(scenario, tmp_path):
    result = ui.run_scenario(scenario, tmp_path)
    assert result["passed"], result.get("error", result)
    assert result["interactions"], "Must drive real Qt mouse/keyboard events"
