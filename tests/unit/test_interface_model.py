"""Tests for models/interface.py — MWU custom validators and schema rules."""

import re

import pytest
from pydantic import ValidationError

from models.interface import (
    Controller,
    GamepadController,
    InterfaceModel,
    Option,
    OptionCase,
    Resource,
    Win32Controller,
    validate_regex,
    _pipeline_override_contains_attach_option,
)


class _FakeFieldInfo:
    """Minimal stand-in for ValidationInfo."""

    def __init__(self, field_name: str = "test"):
        self.field_name = field_name
        self.config = None
        self.data = None
        self.context = None
        self.mode = "python"


# ---------------------------------------------------------------------------
# validate_regex helper
# ---------------------------------------------------------------------------


class TestValidateRegex:
    def test_none_passed_through(self):
        assert validate_regex(None, _FakeFieldInfo()) is None

    def test_valid_string_compiled(self):
        result = validate_regex(r"\d+", _FakeFieldInfo())
        assert isinstance(result, re.Pattern)
        assert result.match("123")

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError, match="无法编译为正则表达式"):
            validate_regex(r"[invalid", _FakeFieldInfo())


# ---------------------------------------------------------------------------
# _pipeline_override_contains_attach_option — representative cases
# ---------------------------------------------------------------------------


class TestPipelineOverrideContainsAttachOption:
    def test_direct_attach(self):
        assert _pipeline_override_contains_attach_option(
            {"attach": {"my_option": "value"}}, "my_option"
        )

    def test_nested_and_list(self):
        assert _pipeline_override_contains_attach_option(
            {"a": {"b": [{"attach": {"my_option": 1}}]}}, "my_option"
        )
        assert not _pipeline_override_contains_attach_option(
            {"attach": {"other": "value"}}, "my_option"
        )


# ---------------------------------------------------------------------------
# Win32Controller — method→int coercion (MWU custom)
# ---------------------------------------------------------------------------


class TestWin32Controller:
    def test_string_method_converted_to_int(self):
        ctrl = Win32Controller(mouse="Seize", keyboard="SendMessage", screencap="GDI")
        assert ctrl.mouse == 1
        assert ctrl.keyboard == 2
        assert ctrl.screencap == 1

    def test_invalid_method_raises(self):
        with pytest.raises(ValidationError):
            Win32Controller.model_validate({"mouse": "InvalidMethod"})

    def test_regex_fields_compiled(self):
        ctrl = Win32Controller.model_validate(
            {"class_regex": r"^Qt.*", "window_regex": r".*MyApp.*"}
        )
        assert isinstance(ctrl.class_regex, re.Pattern)


# ---------------------------------------------------------------------------
# GamepadController — method→int coercion
# ---------------------------------------------------------------------------


class TestGamepadController:
    def test_gamepad_type_default_converted(self):
        """Default 'Xbox360' is converted to int 0 by method_to_int."""
        ctrl = GamepadController()
        assert ctrl.gamepad_type == 0

    def test_dualshock4_converted(self):
        ctrl = GamepadController(gamepad_type="DualShock4")
        assert ctrl.gamepad_type == 1


# ---------------------------------------------------------------------------
# Controller — display field mutual exclusion (MWU custom)
# ---------------------------------------------------------------------------


class TestController:
    def test_display_short_side_and_long_side_mutual_exclusion(self):
        with pytest.raises(ValidationError, match="互斥"):
            Controller(
                name="c", type="Adb", display_short_side=1080, display_long_side=1920
            )

    def test_display_short_side_and_raw_mutual_exclusion(self):
        with pytest.raises(ValidationError, match="互斥"):
            Controller(name="c", type="Adb", display_short_side=1080, display_raw=True)

    def test_display_short_side_default_no_conflict(self):
        """Default 720 should not trigger conflict."""
        ctrl = Controller(name="c", type="Adb", display_long_side=1920)
        assert ctrl.display_long_side == 1920


# ---------------------------------------------------------------------------
# Option — type-specific validators (MWU custom)
# ---------------------------------------------------------------------------


class TestOption:
    def test_select_requires_cases(self):
        with pytest.raises(ValidationError, match="cases 不能为空"):
            Option(type="select")

    def test_switch_requires_two_cases(self):
        with pytest.raises(ValidationError, match="必须有且仅有 2 个元素"):
            Option(type="switch", cases=[OptionCase(name="a")])

    def test_checkbox_requires_cases_and_list_default(self):
        with pytest.raises(ValidationError, match="cases 不能为空"):
            Option(type="checkbox")
        with pytest.raises(ValidationError, match="default_case 必须为字符串数组"):
            Option(type="checkbox", cases=[OptionCase(name="a")], default_case="a")

    def test_input_requires_inputs(self):
        with pytest.raises(ValidationError, match="inputs 不能为空"):
            Option(type="input")

    def test_scan_select_requires_fields(self):
        with pytest.raises(ValidationError, match="scan_dir 不能为空"):
            Option(type="scan_select")
        with pytest.raises(ValidationError, match="scan_filter 不能为空"):
            Option(type="scan_select", scan_dir="images")
        with pytest.raises(ValidationError, match="pipeline_override 不能为空"):
            Option(type="scan_select", scan_dir="images", scan_filter="*.png")

    def test_select_default_case_must_be_str(self):
        with pytest.raises(ValidationError, match="default_case 必须为字符串"):
            Option(type="select", cases=[OptionCase(name="a")], default_case=["a"])


# ---------------------------------------------------------------------------
# InterfaceModel — label/title defaults, import alias, scan_select placeholder
# ---------------------------------------------------------------------------


@pytest.fixture
def _base_iface_data():
    return {
        "interface_version": 2,
        "name": "Test",
        "controller": [Controller(name="adb", type="Adb")],
        "resource": [Resource(name="main", path=["resource"])],
    }


class TestInterfaceModel:
    def test_label_defaults_from_name(self, _base_iface_data):
        model = InterfaceModel(**_base_iface_data)
        assert model.label == "Test"

    def test_title_set_when_label_and_version_present(self, _base_iface_data):
        data = {**_base_iface_data, "label": "My Game", "version": "1.0.0"}
        model = InterfaceModel.model_validate(data)
        assert model.title == "My Game 1.0.0"

    def test_import_alias(self, _base_iface_data):
        model = InterfaceModel(**_base_iface_data, **{"import": ["tasks.json5"]})
        assert model.import_ == ["tasks.json5"]

    def test_scan_select_pipeline_override_valid(self, _base_iface_data):
        """pipeline_override must contain the option name in any-level attach."""
        data = {
            **_base_iface_data,
            "option": {
                "skin": {
                    "type": "scan_select",
                    "scan_dir": "images",
                    "scan_filter": "*.png",
                    "pipeline_override": {"Action": {"attach": {"skin": "{{}}"}}},
                }
            },
        }
        model = InterfaceModel.model_validate(data)
        assert model.option is not None
        assert model.option["skin"].type == "scan_select"

    def test_scan_select_pipeline_override_missing_attach(self, _base_iface_data):
        data = {
            **_base_iface_data,
            "option": {
                "skin": {
                    "type": "scan_select",
                    "scan_dir": "images",
                    "scan_filter": "*.png",
                    "pipeline_override": {"Action": {}},
                }
            },
        }
        with pytest.raises(ValidationError, match="至少包含一次键"):
            InterfaceModel.model_validate(data)
