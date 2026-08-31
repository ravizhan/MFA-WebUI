"""Tests for hotkey conversion and pipeline override placeholders."""

from types import SimpleNamespace

import pytest

from maa_worker.hotkey import hotkey_value_to_codes, split_hotkey_combo
from maa_worker.pipeline_override import PipelineOverrideService
from models.interface import Controller, HotkeyCase, Option


class TestSplitHotkeyCombo:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("", ("", [])),
            (" + ", ("", [])),
            ("A", ("A", [])),
            (" ALT + Shift + A ", ("A", ["ALT", "Shift"])),
        ],
    )
    def test_primary_is_last_nonempty_part(self, value, expected):
        assert split_hotkey_combo(value) == expected


class TestHotkeyValueToCodes:
    @pytest.mark.parametrize(
        ("controller_type", "expected"),
        [
            ("Win32", (0x41, 0x12, 0)),
            ("Adb", (29, 57, 0)),
            ("WlRoots", (30, 56, 0)),
            (None, (0x41, 0x12, 0)),
            ("UnknownController", (0x41, 0x12, 0)),
        ],
    )
    def test_alt_a_uses_controller_key_map(self, controller_type, expected):
        assert hotkey_value_to_codes("ALT+A", controller_type) == expected

    def test_unknown_key_and_empty_value_use_zero_codes(self):
        assert hotkey_value_to_codes("ALT+Unknown", "Win32") == (0, 0x12, 0)
        assert hotkey_value_to_codes("", "Win32") == (0, 0, 0)


class TestPipelineOverrideHotkey:
    def test_replaces_modifier_and_primary_placeholders_with_integers(self):
        option = Option(
            type="hotkey",
            hotkeys=[HotkeyCase(name="FightCombo")],
            pipeline_override={
                "key": [
                    "{FightCombo.modifier1}",
                    "{FightCombo.primary}",
                ]
            },
        )
        worker = SimpleNamespace(
            interface=SimpleNamespace(option={"K": option}),
            device=SimpleNamespace(
                get_active_controller_definitions=lambda: [
                    Controller(name="win", type="Win32")
                ]
            ),
            device_state=SimpleNamespace(current_resource_name=None),
        )
        service = PipelineOverrideService(worker)

        override = service._build_option_override(
            "K",
            {"K": {"FightCombo": "ALT+A"}},
            set(),
        )

        assert override == {"key": [0x12, 0x41]}
