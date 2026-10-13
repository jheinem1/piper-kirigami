# SPDX-License-Identifier: GPL-2.0-or-later
"""Isolate native Breeze QA from the saved Basic-style UI regression suites."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = [
    "overview",
    "mapping",
    "gshift",
    "led",
    "profiles_and_sensitivity",
    "all_assignments",
    "keyboard",
    "all_targets",
    "selection_reveal",
    "narrow_targets",
    "hover_feedback",
    "minimum_size",
    "search",
    "footer",
    "hig_accessibility",
    "error_recovery",
    "assignment_navigation",
    "scoped_assignments",
    "quick_macro",
    "value_picker",
    "visual_events",
]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_native_kde_ui(scenario, tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / ".deps"), str(ROOT), env.get("PYTHONPATH", "")]
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/verify-kde-ui.py"),
            "--scenario",
            scenario,
            "--output",
            str(tmp_path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((tmp_path / "kde-ui-verification.json").read_text())
    assert report["passed"]
    result = report["results"][0]
    assert result["scenario"] == scenario
    assert result["interactions"], "Must drive real Qt mouse/keyboard events"
    assert result["qml_warnings"] == []
    if scenario == "search":
        assert result["persistent_inline_results"]
        assert result["inline_assignment_count"] == 40
        assert result["native_inline_row_sizing"]
        assert result["repeat_activation_and_layer_refresh"]
    if scenario == "overview":
        assert result["layer_control"] == "TabBar: Normal / G-Shift"
        assert result["layer_control_sizes_checked"] == [
            [1400, 820],
            [1200, 820],
            [960, 700],
        ]
    if scenario == "search":
        assert result["tab_search_state_sync"]
    if scenario == "footer":
        assert not result["defaults_supported"]
        assert result["unsupported_defaults_disabled_without_placeholder"]
        assert result["handbook_opened_by_footer_mouse_and_keyboard"]
        assert result["footer_keyboard_order"] == [
            "helpButton",
            "resetButton",
            "applyButton",
        ]
        assert result["reset_transport_writes"] == 0
        assert result["apply_attempts_while_busy"] == 1
        assert result["mock_failure_disconnect_busy_guards"]
    if scenario == "hig_accessibility":
        assert result["accessible_controls_checked"]
        assert result["mapping_font_points_checked"] == [11, 14]
        assert result["native_visual_event_keyboard"]
        assert result["large_font_validation_revealed"]
        assert result["event_panel_fills_to_footer"]
        assert result["compact_rows_and_long_list_keyboard_scroll"]
    if scenario == "error_recovery":
        assert result["new_error_after_dismiss_visible"]
        assert result["led_validation_reset_on_open_and_invalid_input"]
        assert result["transport_writes"] == 0

    if scenario == "assignment_navigation":
        assert len(result["guarded_navigation_routes"]) == 10
        assert result["explicit_scoped_writes"] == 1
    if scenario == "scoped_assignments":
        assert result["child_mapping_writes"] == 1
        assert result["main_profile_mapping_writes"] == 2
        assert result["unrelated_drafts_preserved"]
        assert result["main_revert_scope_preserved"]
        assert result["busy_editor_and_navigation_guarded"]
        assert result["busy_apply_attempts"] == 1
    if scenario == "quick_macro":
        assert result["direct_inline_recording"]
        assert result["empty_and_unknown_chords_rejected"]
        assert result["recording_blocks_navigation_and_shortcuts"]
        assert result["cancel_and_revert_no_writes"]
        assert result["transport_writes"] == 0

    if scenario == "value_picker":
        assert result["full_key_choice_count"] == 767
        assert result["full_mouse_choice_count"] == 32
        assert result["search_arrows_enter_escape_cancel"]
        assert result["focus_returns_to_opener"]
        assert result["selection_only_mutates_local_draft"]
        assert result["explicit_ok_required_and_cancel_preserves_pending_choice"]
        assert result["stale_context_rejected"]
        assert result["transport_writes"] == 0

    if scenario == "visual_events":
        assert result["visual_add_cancel_replace_remove_reorder"]
        assert result["incomplete_sequence_blocks_apply"]
        assert result["generic_delay_supported"]
        assert result["repeated_keyboard_move_tracks_event"]
        assert result["reorder_edge_focus_is_safe"]
        assert result["g600_complete_key_choice_count"] == 135
        assert result["reserved_zero_not_selectable"]
        assert result["explicit_scoped_writes"] == 1
