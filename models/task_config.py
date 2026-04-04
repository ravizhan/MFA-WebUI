from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.interface import InterfaceModel, Option, Preset, PresetOptionValue
from models.scheduler import TaskOptionValue

CUSTOM_PRESET_NAME = "__mwu_reserved_custom_preset__"


class TaskPresetSnapshotModel(BaseModel):
    taskOrder: list[str] = Field(
        default_factory=list, description="任务ID列表（有序，表示执行顺序）"
    )
    taskChecked: dict[str, bool] = Field(
        default_factory=dict,
        description="任务选中状态映射，key为任务ID，value为是否选中",
    )
    taskOptions: dict[str, TaskOptionValue] = Field(
        default_factory=dict, description="任务选项配置，key为选项名，value为选项值"
    )


class TaskConfigModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    selectedPreset: str = Field(
        default=CUSTOM_PRESET_NAME, description="当前选中的预设名称"
    )
    presets: dict[str, TaskPresetSnapshotModel] = Field(
        default_factory=dict, description="所有预设对应的任务快照"
    )

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_config(cls, value: Any):
        if not isinstance(value, dict):
            return value

        if isinstance(value.get("presets"), dict):
            selected_preset = value.get("selectedPreset")
            return {
                **value,
                "selectedPreset": _normalize_preset_name(selected_preset),
            }

        return _migrate_legacy_config(value)


def normalize_task_config(
    config: TaskConfigModel, interface_model: InterfaceModel
) -> TaskConfigModel:
    preset_snapshots: dict[str, TaskPresetSnapshotModel] = {}

    custom_snapshot = config.presets.get(CUSTOM_PRESET_NAME)
    preset_snapshots[CUSTOM_PRESET_NAME] = normalize_snapshot(
        custom_snapshot, interface_model
    )

    for preset in interface_model.preset or []:
        persisted_snapshot = config.presets.get(preset.name)
        snapshot = persisted_snapshot or build_interface_preset_snapshot(
            interface_model, preset
        )
        preset_snapshots[preset.name] = normalize_snapshot(snapshot, interface_model)

    selected_preset = _normalize_preset_name(config.selectedPreset)
    if selected_preset not in preset_snapshots:
        selected_preset = CUSTOM_PRESET_NAME

    return TaskConfigModel(
        selectedPreset=selected_preset,
        presets=preset_snapshots,
    )


def normalize_snapshot(
    snapshot: TaskPresetSnapshotModel | dict[str, Any] | None,
    interface_model: InterfaceModel,
) -> TaskPresetSnapshotModel:
    default_task_order = _build_default_task_order(interface_model)
    valid_task_ids = set(default_task_order)
    normalized_order: list[str] = []
    seen_task_ids: set[str] = set()

    if snapshot is None:
        raw_task_order: list[Any] = []
        raw_task_checked: dict[str, Any] = {}
        raw_task_options: dict[str, Any] = {}
    else:
        snapshot_model = (
            snapshot
            if isinstance(snapshot, TaskPresetSnapshotModel)
            else TaskPresetSnapshotModel(**snapshot)
        )
        raw_task_order = snapshot_model.taskOrder
        raw_task_checked = snapshot_model.taskChecked
        raw_task_options = snapshot_model.taskOptions

    for task_id in raw_task_order:
        if not isinstance(task_id, str):
            continue
        if task_id in valid_task_ids and task_id not in seen_task_ids:
            normalized_order.append(task_id)
            seen_task_ids.add(task_id)

    for task_id in default_task_order:
        if task_id not in seen_task_ids:
            normalized_order.append(task_id)

    normalized_checked = {task_id: False for task_id in default_task_order}
    for task_id, checked in raw_task_checked.items():
        if task_id in valid_task_ids:
            normalized_checked[task_id] = bool(checked)

    option_defaults, option_value_types = _build_option_defaults(interface_model)
    normalized_options = dict(option_defaults)
    for option_key, option_value in raw_task_options.items():
        expected_type = option_value_types.get(option_key)
        if expected_type == "string" and isinstance(option_value, str):
            normalized_options[option_key] = option_value
        elif expected_type == "string_list" and isinstance(option_value, list):
            normalized_options[option_key] = [
                item for item in option_value if isinstance(item, str)
            ]

    return TaskPresetSnapshotModel(
        taskOrder=normalized_order,
        taskChecked=normalized_checked,
        taskOptions=normalized_options,
    )


def build_interface_preset_snapshot(
    interface_model: InterfaceModel, preset: Preset
) -> TaskPresetSnapshotModel:
    option_defaults, _ = _build_option_defaults(interface_model)
    task_order = _build_default_task_order(interface_model)
    task_checked = {task_id: False for task_id in task_order}
    task_name_to_entry = {
        task.name: task.entry for task in (interface_model.task or [])
    }
    option_map = interface_model.option or {}

    ordered_preset_tasks: list[str] = []
    seen_task_ids: set[str] = set()

    for preset_task in preset.task or []:
        task_entry = task_name_to_entry.get(preset_task.name)
        if not task_entry or task_entry in seen_task_ids:
            continue

        ordered_preset_tasks.append(task_entry)
        seen_task_ids.add(task_entry)
        task_checked[task_entry] = bool(
            True if preset_task.enabled is None else preset_task.enabled
        )

        for option_name, option_value in (preset_task.option or {}).items():
            _apply_preset_option_value(
                option_name, option_value, option_map, option_defaults
            )

    normalized_order = ordered_preset_tasks + [
        task_id for task_id in task_order if task_id not in seen_task_ids
    ]

    return TaskPresetSnapshotModel(
        taskOrder=normalized_order,
        taskChecked=task_checked,
        taskOptions=option_defaults,
    )


def _migrate_legacy_config(value: dict[str, Any]) -> dict[str, Any]:
    selected_preset = _normalize_preset_name(value.get("selectedPreset"))
    presets: dict[str, dict[str, Any]] = {}

    legacy_current_snapshot = _build_legacy_snapshot(
        value.get("taskOrder"),
        value.get("taskChecked"),
        value.get("taskOptions"),
    )
    legacy_custom_snapshot = _build_legacy_snapshot(
        value.get("customTaskOrder"),
        value.get("customTaskChecked"),
        value.get("customTaskOptions"),
    )

    if selected_preset == CUSTOM_PRESET_NAME:
        if _snapshot_has_content(legacy_current_snapshot):
            presets[CUSTOM_PRESET_NAME] = legacy_current_snapshot
        elif _snapshot_has_content(legacy_custom_snapshot):
            presets[CUSTOM_PRESET_NAME] = legacy_custom_snapshot
    else:
        if _snapshot_has_content(legacy_current_snapshot):
            presets[selected_preset] = legacy_current_snapshot
        if _snapshot_has_content(legacy_custom_snapshot):
            presets[CUSTOM_PRESET_NAME] = legacy_custom_snapshot

    if (
        selected_preset != CUSTOM_PRESET_NAME
        and CUSTOM_PRESET_NAME not in presets
        and _snapshot_has_content(legacy_custom_snapshot)
    ):
        presets[CUSTOM_PRESET_NAME] = legacy_custom_snapshot

    return {
        "selectedPreset": selected_preset,
        "presets": presets,
    }


def _build_legacy_snapshot(
    task_order: Any, task_checked: Any, task_options: Any
) -> dict[str, Any]:
    normalized_order = (
        [item for item in task_order if isinstance(item, str)]
        if isinstance(task_order, list)
        else []
    )
    normalized_checked = (
        {
            key: bool(value)
            for key, value in task_checked.items()
            if isinstance(key, str)
        }
        if isinstance(task_checked, dict)
        else {}
    )
    normalized_options = (
        {key: value for key, value in task_options.items() if isinstance(key, str)}
        if isinstance(task_options, dict)
        else {}
    )

    return {
        "taskOrder": normalized_order,
        "taskChecked": normalized_checked,
        "taskOptions": normalized_options,
    }


def _snapshot_has_content(snapshot: dict[str, Any]) -> bool:
    return bool(
        snapshot["taskOrder"] or snapshot["taskChecked"] or snapshot["taskOptions"]
    )


def _normalize_preset_name(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return CUSTOM_PRESET_NAME


def _build_default_task_order(interface_model: InterfaceModel) -> list[str]:
    return [task.entry for task in (interface_model.task or [])]


def _build_option_defaults(
    interface_model: InterfaceModel,
) -> tuple[dict[str, TaskOptionValue], dict[str, str]]:
    defaults: dict[str, TaskOptionValue] = {}
    value_types: dict[str, str] = {}

    for option_name, option in (interface_model.option or {}).items():
        if option.type in {"select", "scan_select", "switch"}:
            default_value = option.default_case or (
                option.cases[0].name if option.cases else ""
            )
            defaults[option_name] = (
                default_value if isinstance(default_value, str) else ""
            )
            value_types[option_name] = "string"
            continue

        if option.type == "input":
            for input_case in option.inputs or []:
                input_key = f"{option_name}_{input_case.name}"
                defaults[input_key] = input_case.default or ""
                value_types[input_key] = "string"
            continue

        if option.type == "checkbox":
            selected_values = (
                set(option.default_case)
                if isinstance(option.default_case, list)
                else set()
            )
            defaults[option_name] = [
                case.name
                for case in (option.cases or [])
                if case.name in selected_values
            ]
            value_types[option_name] = "string_list"

    return defaults, value_types


def _apply_preset_option_value(
    option_name: str,
    value: PresetOptionValue,
    option_map: dict[str, Option],
    target_options: dict[str, TaskOptionValue],
) -> None:
    option = option_map.get(option_name)
    if option is None:
        return

    if option.type == "input":
        if not isinstance(value, dict):
            return
        for input_case in option.inputs or []:
            input_value = value.get(input_case.name)
            if isinstance(input_value, str):
                target_options[f"{option_name}_{input_case.name}"] = input_value
        return

    if option.type == "checkbox":
        if isinstance(value, list):
            target_options[option_name] = [
                item for item in value if isinstance(item, str)
            ]
        return

    if isinstance(value, str):
        target_options[option_name] = value
