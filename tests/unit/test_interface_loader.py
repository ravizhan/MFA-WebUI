"""Tests for models/interface_loader.py — interface loading, merging, scanning."""

import json as stdlib_json
from pathlib import Path

import pytest

from models.interface import InterfaceModel
from models.interface_loader import (
    InterfaceLoadError,
    _normalize_import_list,
    _normalize_root_relative_path,
    _read_json_dict,
    _register_options,
    _register_presets,
    _register_tasks,
    _resolve_import_path,
    _MergeState,
    _validate_importable_fragment,
    _scan_scan_select_cases,
    load_interface_model,
    resolve_interface_relative_path,
    rescan_scan_select_option,
)


# ---------------------------------------------------------------------------
# Path safety / traversal
# ---------------------------------------------------------------------------


class TestNormalizeRootRelativePath:
    def test_normal_and_backslash(self):
        assert (
            _normalize_root_relative_path("resource/sub", field_name="p")
            == "resource/sub"
        )
        assert (
            _normalize_root_relative_path(r"resource\sub", field_name="p")
            == "resource/sub"
        )

    def test_rejects_empty_absolute_and_traversal(self):
        with pytest.raises(ValueError, match="不能为空"):
            _normalize_root_relative_path("", field_name="p")
        with pytest.raises(ValueError, match="不允许使用绝对路径"):
            _normalize_root_relative_path("/etc/passwd", field_name="p")
        with pytest.raises(ValueError, match="不允许包含"):
            _normalize_root_relative_path("a/../b", field_name="p")


class TestResolveImportPath:
    def test_valid(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "tasks.json5").write_text("{}")
        result = _resolve_import_path("sub/tasks.json5", tmp_path)
        assert result == (tmp_path / "sub" / "tasks.json5").resolve()

    def test_traversal_raises(self, tmp_path):
        with pytest.raises(ValueError, match="不允许包含"):
            _resolve_import_path("../other.json5", tmp_path)


class TestResolveInterfaceRelativePath:
    def test_valid_file(self, tmp_path):
        (tmp_path / "config.json5").write_text("{}")
        result = resolve_interface_relative_path(tmp_path, "config.json5")
        assert result == (tmp_path / "config.json5").resolve()

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ValueError, match="不存在"):
            resolve_interface_relative_path(tmp_path, "missing.json5")

    def test_traversal_raises(self, tmp_path):
        with pytest.raises(ValueError, match="不允许包含"):
            resolve_interface_relative_path(tmp_path, "../outside.txt")

    def test_dir_ok_when_allowed(self, tmp_path):
        (tmp_path / "somedir").mkdir()
        result = resolve_interface_relative_path(
            tmp_path, "somedir", allow_directories=True
        )
        assert result == (tmp_path / "somedir").resolve()


# ---------------------------------------------------------------------------
# Read / import-list errors (not parser behavior)
# ---------------------------------------------------------------------------


class TestReadJsonDict:
    def test_missing_file(self, tmp_path):
        with pytest.raises(InterfaceLoadError, match="找不到配置文件"):
            _read_json_dict(tmp_path / "nope.json")

    def test_malformed_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{invalid}")
        with pytest.raises(InterfaceLoadError, match="解析配置文件失败"):
            _read_json_dict(p)

    def test_non_dict_root(self, tmp_path):
        p = tmp_path / "arr.json"
        p.write_text("[1, 2, 3]")
        with pytest.raises(InterfaceLoadError, match="必须是 JSON 对象"):
            _read_json_dict(p)


class TestNormalizeImportList:
    def test_none_and_valid(self):
        assert _normalize_import_list(None, Path()) == []
        assert _normalize_import_list(["a.json5"], Path()) == ["a.json5"]

    def test_invalid_shape_raises(self):
        with pytest.raises(InterfaceLoadError, match="非空字符串数组"):
            _normalize_import_list("bad", Path())
        with pytest.raises(InterfaceLoadError, match="非空字符串数组"):
            _normalize_import_list([""], Path())


class TestValidateImportableFragment:
    def test_invalid_keys_reported(self):
        with pytest.raises(InterfaceLoadError, match="非法字段.*extra"):
            _validate_importable_fragment({"task": [], "extra": 1}, Path())


# ---------------------------------------------------------------------------
# Register conflicts
# ---------------------------------------------------------------------------


class TestRegisterTasks:
    def test_invalid_shape_and_conflicts(self):
        with pytest.raises(InterfaceLoadError, match="必须是数组"):
            _register_tasks("bad", Path(), _MergeState())
        state = _MergeState()
        _register_tasks([{"name": "A", "entry": "E"}], Path("/a.json"), state)
        with pytest.raises(InterfaceLoadError, match="冲突"):
            _register_tasks([{"name": "B", "entry": "E"}], Path("/b.json"), state)
        with pytest.raises(InterfaceLoadError, match="冲突"):
            _register_tasks([{"name": "A", "entry": "E2"}], Path("/c.json"), state)


class TestRegisterOptions:
    def test_conflict(self):
        state = _MergeState()
        _register_options({"opt": {}}, Path("/a.json"), state)
        with pytest.raises(InterfaceLoadError, match="冲突"):
            _register_options({"opt": {}}, Path("/b.json"), state)


class TestRegisterPresets:
    def test_conflict(self):
        state = _MergeState()
        _register_presets([{"name": "P"}], Path("/a.json"), state)
        with pytest.raises(InterfaceLoadError, match="冲突"):
            _register_presets([{"name": "P"}], Path("/b.json"), state)


# ---------------------------------------------------------------------------
# scan_select
# ---------------------------------------------------------------------------


class TestScanScanSelectCases:
    def test_rejects_prefilled_and_missing_fields(self, tmp_path):
        with pytest.raises(InterfaceLoadError, match="不允许预置 cases"):
            _scan_scan_select_cases(
                "opt",
                {"cases": [{"name": "a"}], "scan_dir": ".", "scan_filter": "*"},
                Path(),
            )
        with pytest.raises(InterfaceLoadError, match="scan_dir 必须为非空字符串"):
            _scan_scan_select_cases("opt", {"scan_dir": "", "scan_filter": "*"}, Path())
        with pytest.raises(InterfaceLoadError, match="不存在或不是目录"):
            _scan_scan_select_cases(
                "opt", {"scan_dir": "nonexistent", "scan_filter": "*"}, tmp_path
            )

    def test_returns_matched_files(self, tmp_path):
        imgs = tmp_path / "images"
        imgs.mkdir()
        (imgs / "icon1.png").write_text("x")
        (imgs / "icon2.png").write_text("x")
        (imgs / "readme.txt").write_text("x")

        result = _scan_scan_select_cases(
            "opt", {"scan_dir": "images", "scan_filter": "*.png"}, tmp_path
        )
        assert {c["name"] for c in result} == {"icon1.png", "icon2.png"}


class TestRescanScanSelectOption:
    def test_nonexistent_and_wrong_type_raise(self, tmp_path):
        iface = InterfaceModel.model_validate(
            {
                "interface_version": 2,
                "name": "T",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "r", "path": ["resource"]}],
                "option": {"diff": {"type": "select", "cases": [{"name": "a"}]}},
            }
        )
        with pytest.raises(InterfaceLoadError, match="不存在"):
            rescan_scan_select_option(iface, "no_such_option", tmp_path)
        with pytest.raises(InterfaceLoadError, match="不是 scan_select"):
            rescan_scan_select_option(iface, "diff", tmp_path)

    def test_rescan_populates_cases(self, tmp_path):
        imgs = tmp_path / "images"
        imgs.mkdir()
        (imgs / "skin_1.png").write_text("x")
        (imgs / "skin_2.png").write_text("x")

        iface = InterfaceModel.model_validate(
            {
                "interface_version": 2,
                "name": "T",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "r", "path": ["resource"]}],
                "option": {
                    "skin": {
                        "type": "scan_select",
                        "scan_dir": "images",
                        "scan_filter": "*.png",
                        "pipeline_override": {"attach": {"skin": ""}},
                    }
                },
            }
        )
        scanned = rescan_scan_select_option(iface, "skin", tmp_path)
        assert {c["name"] for c in scanned} == {"skin_1.png", "skin_2.png"}
        assert iface.option is not None
        assert len(iface.option["skin"].cases) == 2


# ---------------------------------------------------------------------------
# load_interface_model — public integration
# ---------------------------------------------------------------------------


def _write_interface(base_dir: Path, data: dict):
    (base_dir / "interface.json").write_text(stdlib_json.dumps(data))


class TestLoadInterfaceModel:
    def test_no_interface_json(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with pytest.raises(InterfaceLoadError, match="找不到配置文件"):
            load_interface_model(empty_dir)

    def test_minimal_interface(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
            },
        )
        model = load_interface_model(tmp_path)
        assert model.name == "Test"

    def test_invalid_interface_version(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 1,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
            },
        )
        with pytest.raises(InterfaceLoadError, match="校验 interface 配置失败"):
            load_interface_model(tmp_path)

    def test_import_file_loaded(self, tmp_path):
        (tmp_path / "tasks.json5").write_text(
            '{task: [{name: "Extra", entry: "Extra"}]}'
        )
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "import": ["tasks.json5"],
            },
        )
        model = load_interface_model(tmp_path)
        assert model.task is not None
        assert {t.name for t in model.task} == {"Extra"}

    def test_nonexistent_imports_raises(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "import": ["missing.json5"],
            },
        )
        with pytest.raises(InterfaceLoadError, match="找不到配置文件"):
            load_interface_model(tmp_path)

    def test_cyclic_import_raises(self, tmp_path):
        (tmp_path / "a.json5").write_text('{import: ["b.json5"]}')
        (tmp_path / "b.json5").write_text('{import: ["a.json5"]}')
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "import": ["a.json5"],
            },
        )
        with pytest.raises(InterfaceLoadError, match="循环导入"):
            load_interface_model(tmp_path)

    def test_import_conflict_entry(self, tmp_path):
        (tmp_path / "extra.json5").write_text(
            '{task: [{name: "X", entry: "RootTask"}]}'
        )
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "RootTask", "entry": "RootTask"}],
                "import": ["extra.json5"],
            },
        )
        with pytest.raises(InterfaceLoadError, match="冲突"):
            load_interface_model(tmp_path)

    def test_import_fragment_with_illegal_key(self, tmp_path):
        (tmp_path / "bad.json5").write_text("{controller: []}")
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "import": ["bad.json5"],
            },
        )
        with pytest.raises(InterfaceLoadError, match="非法字段"):
            load_interface_model(tmp_path)

    def test_nonexistent_resource_and_controller(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "T", "entry": "T", "resource": ["bad_resource"]}],
            },
        )
        with pytest.raises(InterfaceLoadError, match="引用了不存在的 resource"):
            load_interface_model(tmp_path)

        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "T", "entry": "T", "controller": ["bad_ctrl"]}],
            },
        )
        with pytest.raises(InterfaceLoadError, match="引用了不存在的 controller"):
            load_interface_model(tmp_path)

    def test_scan_select_expansion(self, tmp_path):
        imgs = tmp_path / "images"
        imgs.mkdir()
        (imgs / "a.png").write_text("x")
        (imgs / "b.png").write_text("x")
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "option": {
                    "skin": {
                        "type": "scan_select",
                        "scan_dir": "images",
                        "scan_filter": "*.png",
                        "pipeline_override": {"Action": {"attach": {"skin": ""}}},
                    }
                },
            },
        )
        model = load_interface_model(tmp_path)
        assert model.option is not None
        assert model.option["skin"].cases is not None
        assert len(model.option["skin"].cases) == 2

    def test_preset_duplicate_task(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A"}],
                "preset": [{"name": "P", "task": [{"name": "A"}, {"name": "A"}]}],
            },
        )
        with pytest.raises(InterfaceLoadError, match="重复任务"):
            load_interface_model(tmp_path)

    def test_preset_nonexistent_task(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A"}],
                "preset": [{"name": "P", "task": [{"name": "NoSuchTask"}]}],
            },
        )
        with pytest.raises(InterfaceLoadError, match="引用了不存在的任务"):
            load_interface_model(tmp_path)

    def test_preset_option_not_in_task(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A"}],
                "option": {"diff": {"type": "select", "cases": [{"name": "easy"}]}},
                "preset": [
                    {"name": "P", "task": [{"name": "A", "option": {"diff": "easy"}}]}
                ],
            },
        )
        with pytest.raises(InterfaceLoadError, match="不属于该任务的选项"):
            load_interface_model(tmp_path)

    def test_preset_select_invalid_case(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A", "option": ["diff"]}],
                "option": {"diff": {"type": "select", "cases": [{"name": "easy"}]}},
                "preset": [
                    {"name": "P", "task": [{"name": "A", "option": {"diff": "hard"}}]}
                ],
            },
        )
        with pytest.raises(InterfaceLoadError, match="引用了不存在的 case"):
            load_interface_model(tmp_path)

    def test_preset_checkbox_and_input_invalid(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A", "option": ["mods"]}],
                "option": {
                    "mods": {
                        "type": "checkbox",
                        "cases": [{"name": "fast"}, {"name": "slow"}],
                    }
                },
                "preset": [
                    {
                        "name": "P",
                        "task": [{"name": "A", "option": {"mods": "not_a_list"}}],
                    }
                ],
            },
        )
        with pytest.raises(InterfaceLoadError, match="必须是字符串数组"):
            load_interface_model(tmp_path)

        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A", "option": ["cfg"]}],
                "option": {"cfg": {"type": "input", "inputs": [{"name": "host"}]}},
                "preset": [
                    {
                        "name": "P",
                        "task": [
                            {"name": "A", "option": {"cfg": "string_instead_of_dict"}}
                        ],
                    }
                ],
            },
        )
        with pytest.raises(InterfaceLoadError, match="必须是对象"):
            load_interface_model(tmp_path)

        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A", "option": ["cfg"]}],
                "option": {"cfg": {"type": "input", "inputs": [{"name": "host"}]}},
                "preset": [
                    {
                        "name": "P",
                        "task": [{"name": "A", "option": {"cfg": {"bad_key": "val"}}}],
                    }
                ],
            },
        )
        with pytest.raises(InterfaceLoadError, match="引用了不存在的输入项"):
            load_interface_model(tmp_path)
