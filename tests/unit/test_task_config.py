"""Tests for models/task_config.py — public normalization and snapshot flows."""

from models.interface import (
    InterfaceModel,
    Controller,
    Resource,
    Task,
    Option,
    OptionCase,
    InputCase,
    Preset,
    PresetTask,
)
from models.task_config import (
    CUSTOM_PRESET_NAME,
    TaskConfigModel,
    build_interface_preset_snapshot,
    normalize_snapshot,
    normalize_task_config,
    normalize_task_execution_payload,
    normalize_task_options_by_task,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_interface(
    tasks=None, options=None, presets=None, resources=None, controllers=None
):
    return InterfaceModel(
        interface_version=2,
        name="Test",
        label="Test",
        controller=controllers or [Controller(name="adb", type="Adb")],
        resource=resources or [Resource(name="main", path=["resource"])],
        task=tasks or [],
        option=options or None,
        preset=presets or None,
    )


def _make_option(
    opt_type="select",
    cases=None,
    inputs=None,
    default_case=None,
    scan_dir=None,
    scan_filter=None,
    pipeline_override=None,
):
    return Option(
        type=opt_type,
        cases=[OptionCase(name=c) if isinstance(c, str) else c for c in (cases or [])],
        inputs=inputs,
        default_case=default_case,
        scan_dir=scan_dir,
        scan_filter=scan_filter,
        pipeline_override=pipeline_override,
    )


# ---------------------------------------------------------------------------
# normalize_task_options_by_task
# ---------------------------------------------------------------------------


class TestNormalizeTaskOptionsByTask:
    def test_basic(self):
        iface = _make_interface(
            tasks=[Task(name="T1", entry="T1", option=["diff"])],
            options={"diff": _make_option("select", cases=["a", "b"])},
        )
        result = normalize_task_options_by_task({"T1": {"diff": "b"}}, ["T1"], iface)
        assert result["T1"]["diff"] == "b"


# ---------------------------------------------------------------------------
# normalize_task_execution_payload
# ---------------------------------------------------------------------------


class TestNormalizeTaskExecutionPayload:
    def test_dedups_filters_and_orders(self):
        iface = _make_interface(
            tasks=[Task(name="A", entry="TaskA"), Task(name="B", entry="TaskB")],
        )
        task_list, _, _ = normalize_task_execution_payload(
            ["TaskA", "TaskB", "TaskA", "InvalidTask"],
            {},
            iface,
        )
        assert task_list == ["TaskA", "TaskB"]

        task_list, _, _ = normalize_task_execution_payload(
            ["TaskB", "TaskA"],
            {},
            iface,
        )
        assert task_list == ["TaskB", "TaskA"]

    def test_normalizes_task_options(self):
        iface = _make_interface(
            tasks=[Task(name="A", entry="A", option=["diff"])],
            options={"diff": _make_option("select", cases=["easy", "hard"])},
        )
        _, options, _ = normalize_task_execution_payload(
            ["A"],
            {"A": {"diff": "hard"}},
            iface,
        )
        assert options["A"]["diff"] == "hard"

    def test_pre_tasks_enabled_filter(self):
        iface = _make_interface()
        _, _, pre_tasks = normalize_task_execution_payload(
            [],
            {},
            iface,
            raw_pre_tasks=[
                {"command": "echo ok", "enabled": True},
                {"command": "echo skip", "enabled": False},
                {"command": "", "enabled": True},
            ],
        )
        assert len(pre_tasks) == 1
        assert pre_tasks[0].command == "echo ok"


# ---------------------------------------------------------------------------
# normalize_snapshot
# ---------------------------------------------------------------------------


class TestNormalizeSnapshot:
    def test_empty_snapshot_defaults(self):
        iface = _make_interface(tasks=[Task(name="A", entry="TaskA")])
        result = normalize_snapshot(None, iface)
        assert "TaskA" in result.taskOrder
        assert result.taskChecked["TaskA"] is False

    def test_removes_invalid_merges_and_dedups(self):
        iface = _make_interface(
            tasks=[Task(name="A", entry="TaskA"), Task(name="B", entry="TaskB")],
        )
        result = normalize_snapshot(
            {
                "taskOrder": ["TaskB", "InvalidTask", "TaskB"],
                "taskChecked": {"TaskB": True},
                "taskOptions": {},
            },
            iface,
        )
        assert "InvalidTask" not in result.taskOrder
        assert result.taskOrder == ["TaskB", "TaskA"]
        assert result.taskChecked["TaskB"] is True
        assert result.taskChecked["TaskA"] is False

    def test_preserves_normalized_pre_tasks(self):
        iface = _make_interface(tasks=[])
        result = normalize_snapshot(
            {
                "taskOrder": [],
                "taskChecked": {},
                "taskOptions": {},
                "preTasks": [{"command": "echo hello"}],
            },
            iface,
        )
        assert len(result.preTasks) == 1
        assert result.preTasks[0].command == "echo hello"


# ---------------------------------------------------------------------------
# build_interface_preset_snapshot
# ---------------------------------------------------------------------------


class TestBuildInterfacePresetSnapshot:
    def test_option_types_applied(self):
        iface = _make_interface(
            tasks=[
                Task(name="T", entry="T", option=["diff", "mods", "cfg"]),
            ],
            options={
                "diff": _make_option("select", cases=["easy", "hard"]),
                "mods": _make_option("checkbox", cases=["a", "b", "c"]),
                "cfg": _make_option(
                    "input", inputs=[InputCase(name="host"), InputCase(name="port")]
                ),
            },
            presets=[
                Preset(
                    name="P",
                    task=[
                        PresetTask(
                            name="T",
                            option={
                                "diff": "hard",
                                "mods": ["a", "c"],
                                "cfg": {"host": "localhost"},
                            },
                        )
                    ],
                )
            ],
        )
        snapshot = build_interface_preset_snapshot(iface, iface.preset[0])
        assert snapshot.taskOptions["T"]["diff"] == "hard"
        assert set(snapshot.taskOptions["T"]["mods"]) == {"a", "c"}
        cfg = snapshot.taskOptions["T"]["cfg"]
        assert isinstance(cfg, dict)
        assert cfg["host"] == "localhost"
        assert cfg["port"] == ""

    def test_enabled_false_stays_unchecked(self):
        iface = _make_interface(
            tasks=[Task(name="T", entry="T")],
            presets=[Preset(name="P", task=[PresetTask(name="T", enabled=False)])],
        )
        snapshot = build_interface_preset_snapshot(iface, iface.preset[0])
        assert snapshot.taskChecked["T"] is False

    def test_duplicate_preset_tasks_deduped(self):
        iface = _make_interface(
            tasks=[Task(name="A", entry="A")],
            presets=[
                Preset(name="P", task=[PresetTask(name="A"), PresetTask(name="A")])
            ],
        )
        snapshot = build_interface_preset_snapshot(iface, iface.preset[0])
        assert snapshot.taskOrder.count("A") == 1


# ---------------------------------------------------------------------------
# normalize_task_config — full flow
# ---------------------------------------------------------------------------


class TestNormalizeTaskConfig:
    def test_empty_config(self):
        iface = _make_interface(tasks=[Task(name="A", entry="A")])
        result = normalize_task_config(TaskConfigModel(), iface)
        assert CUSTOM_PRESET_NAME in result.presets
        assert result.selectedPreset == CUSTOM_PRESET_NAME

    def test_falls_back_to_custom_when_selected_missing(self):
        iface = _make_interface(tasks=[Task(name="A", entry="A")])
        result = normalize_task_config(
            TaskConfigModel(selectedPreset="NonExistent"), iface
        )
        assert result.selectedPreset == CUSTOM_PRESET_NAME

    def test_preserves_valid_selected_preset(self):
        iface = _make_interface(
            tasks=[Task(name="A", entry="A")],
            presets=[Preset(name="QuickRun")],
        )
        config = TaskConfigModel(selectedPreset="QuickRun")
        result = normalize_task_config(config, iface)
        assert result.selectedPreset == "QuickRun"

    def test_includes_interface_preset_when_absent_from_config(self):
        iface = _make_interface(
            tasks=[Task(name="A", entry="A")],
            presets=[Preset(name="QuickRun", task=[PresetTask(name="A")])],
        )
        config = TaskConfigModel(selectedPreset="QuickRun")
        result = normalize_task_config(config, iface)
        assert "QuickRun" in result.presets
        assert "A" in result.presets["QuickRun"].taskOrder


# ---------------------------------------------------------------------------
# TaskConfigModel — persisted raw-config normalization
# ---------------------------------------------------------------------------


class TestTaskConfigModel:
    def test_normalize_raw_config_strips_blank_selected_preset(self):
        model = TaskConfigModel.model_validate({"selectedPreset": "  "})
        assert model.selectedPreset == CUSTOM_PRESET_NAME

    def test_normalize_raw_config_ignores_non_string_preset_names(self):
        model = TaskConfigModel.model_validate({"presets": {1: {"taskOrder": []}}})
        assert model.presets == {}
