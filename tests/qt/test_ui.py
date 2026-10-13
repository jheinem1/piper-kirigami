# SPDX-License-Identifier: GPL-2.0-or-later
"""Integration assertions against native Qt/Kirigami, driven by QTest."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "verify_qt_ui", ROOT / "tools/verify-qt-ui.py"
)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


@pytest.mark.parametrize("scenario", list(ui.SCENARIOS))
def test_native_ui_scenario(scenario, tmp_path):
    result = ui.run_scenario(scenario, tmp_path)
    assert result["passed"], result.get("error", result)
    assert result["interactions"], "Scenario must drive actual Qt mouse/keyboard events"
