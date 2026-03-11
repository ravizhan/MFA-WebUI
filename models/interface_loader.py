from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from models.interface import InterfaceModel


IMPORTABLE_KEYS = {"task", "option", "preset", "import"}


class InterfaceLoadError(ValueError):
    pass


class _MergeState:
    def __init__(self):
        self.task_entries: dict[str, Path] = {}
        self.task_names: dict[str, Path] = {}
        self.option_keys: dict[str, Path] = {}
        self.preset_names: dict[str, Path] = {}


def _read_json_dict(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as exc:
        raise InterfaceLoadError(f"找不到配置文件: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InterfaceLoadError(
            f"解析配置文件失败: {path} (行 {exc.lineno}, 列 {exc.colno}): {exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise InterfaceLoadError(f"配置文件必须是 JSON 对象: {path}")
    return data


def _normalize_import_list(raw_value: Any, source_path: Path) -> list[str]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list) or not all(
        isinstance(item, str) and item for item in raw_value
    ):
        raise InterfaceLoadError(f"import 字段必须是非空字符串数组: {source_path}")
    return raw_value


def _validate_importable_fragment(data: dict[str, Any], source_path: Path) -> None:
    invalid_keys = sorted(set(data) - IMPORTABLE_KEYS)
    if invalid_keys:
        raise InterfaceLoadError(
            f"导入文件只允许包含 task、option、preset、import 字段: {source_path}，"
            f"发现非法字段 {', '.join(invalid_keys)}"
        )


def _raise_conflict(
    kind: str, key: str, source_path: Path, existing_path: Path
) -> None:
    raise InterfaceLoadError(
        f"{kind} 冲突: {key} 已在 {existing_path} 定义，无法再次从 {source_path} 导入"
    )


def _register_tasks(tasks: Any, source_path: Path, state: _MergeState) -> None:
    if tasks is None:
        return
    if not isinstance(tasks, list):
        raise InterfaceLoadError(f"task 字段必须是数组: {source_path}")

    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise InterfaceLoadError(f"task[{index}] 必须是对象: {source_path}")
        task_name = task.get("name")
        task_entry = task.get("entry")
        if not isinstance(task_name, str) or not task_name:
            raise InterfaceLoadError(
                f"task[{index}].name 必须是非空字符串: {source_path}"
            )
        if not isinstance(task_entry, str) or not task_entry:
            raise InterfaceLoadError(
                f"task[{index}].entry 必须是非空字符串: {source_path}"
            )

        existing_entry = state.task_entries.get(task_entry)
        if existing_entry is not None:
            _raise_conflict("task.entry", task_entry, source_path, existing_entry)
        existing_name = state.task_names.get(task_name)
        if existing_name is not None:
            _raise_conflict("task.name", task_name, source_path, existing_name)

        state.task_entries[task_entry] = source_path
        state.task_names[task_name] = source_path


def _register_options(options: Any, source_path: Path, state: _MergeState) -> None:
    if options is None:
        return
    if not isinstance(options, dict):
        raise InterfaceLoadError(f"option 字段必须是对象: {source_path}")

    for option_key in options:
        if not isinstance(option_key, str) or not option_key:
            raise InterfaceLoadError(f"option 键必须是非空字符串: {source_path}")

        existing_path = state.option_keys.get(option_key)
        if existing_path is not None:
            _raise_conflict("option", option_key, source_path, existing_path)
        state.option_keys[option_key] = source_path


def _register_presets(presets: Any, source_path: Path, state: _MergeState) -> None:
    if presets is None:
        return
    if not isinstance(presets, list):
        raise InterfaceLoadError(f"preset 字段必须是数组: {source_path}")

    for index, preset in enumerate(presets):
        if not isinstance(preset, dict):
            raise InterfaceLoadError(f"preset[{index}] 必须是对象: {source_path}")
        preset_name = preset.get("name")
        if not isinstance(preset_name, str) or not preset_name:
            raise InterfaceLoadError(
                f"preset[{index}].name 必须是非空字符串: {source_path}"
            )

        existing_path = state.preset_names.get(preset_name)
        if existing_path is not None:
            _raise_conflict("preset", preset_name, source_path, existing_path)
        state.preset_names[preset_name] = source_path


def _seed_root_sections(
    root_data: dict[str, Any], source_path: Path, state: _MergeState
) -> None:
    _register_tasks(root_data.get("task"), source_path, state)
    _register_options(root_data.get("option"), source_path, state)
    _register_presets(root_data.get("preset"), source_path, state)


def _merge_fragment_sections(
    target: dict[str, Any],
    fragment: dict[str, Any],
    source_path: Path,
    state: _MergeState,
) -> None:
    tasks = fragment.get("task")
    options = fragment.get("option")
    presets = fragment.get("preset")

    _register_tasks(tasks, source_path, state)
    _register_options(options, source_path, state)
    _register_presets(presets, source_path, state)

    if tasks:
        target.setdefault("task", [])
        target["task"].extend(copy.deepcopy(tasks))
    if options:
        target.setdefault("option", {})
        target["option"].update(copy.deepcopy(options))
    if presets:
        target.setdefault("preset", [])
        target["preset"].extend(copy.deepcopy(presets))


def _resolve_import_path(import_path: str, base_dir: Path) -> Path:
    path = Path(import_path)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _merge_imports_into_target(
    target: dict[str, Any],
    import_paths: list[str],
    base_dir: Path,
    state: _MergeState,
    stack: list[Path],
) -> None:
    for import_path in import_paths:
        resolved_path = _resolve_import_path(import_path, base_dir)
        if resolved_path in stack:
            chain = " -> ".join(str(item) for item in [*stack, resolved_path])
            raise InterfaceLoadError(f"检测到循环导入: {chain}")

        fragment = _read_json_dict(resolved_path)
        _validate_importable_fragment(fragment, resolved_path)

        child_imports = _normalize_import_list(fragment.get("import"), resolved_path)
        _merge_imports_into_target(
            target,
            child_imports,
            resolved_path.parent,
            state,
            [*stack, resolved_path],
        )
        _merge_fragment_sections(target, fragment, resolved_path, state)


def load_interface_model(interface_path: str | Path) -> InterfaceModel:
    root_path = Path(interface_path).resolve()
    root_data = _read_json_dict(root_path)
    merged_data = copy.deepcopy(root_data)
    merge_state = _MergeState()

    _seed_root_sections(merged_data, root_path, merge_state)
    root_imports = _normalize_import_list(merged_data.get("import"), root_path)
    _merge_imports_into_target(
        merged_data,
        root_imports,
        root_path.parent,
        merge_state,
        [root_path],
    )

    try:
        return InterfaceModel.model_validate(merged_data)
    except Exception as exc:
        raise InterfaceLoadError(f"校验 interface 配置失败: {exc}") from exc
