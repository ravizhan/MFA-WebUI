import copy
import io
import subprocess
import threading
import time
from importlib import metadata
from pathlib import Path
from queue import SimpleQueue
from typing import Any, cast

import httpx
import plyer
from PIL import Image
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

import json_utils as json
from maa_worker.agent_loader import load_agents, run_black_magic
from maa_worker.device_manager import (
    connect_device as device_connect_device,
    get_controller_definition as device_get_controller_definition,
    get_device as device_get_device,
    set_resource as device_set_resource,
)
from maa_worker.task_runner import (
    run_process as run_task_process,
    start_task as start_worker_task,
    stop_task as stop_worker_task,
)
from models.api import DeviceModel, RealtimeEvent, RealtimeEventLevel, RealtimeEventName
from models.interface import InterfaceModel, PipelineOverride
from models.scheduler import TaskOptionValue
from models.settings import SettingsModel

resource = Resource()
resource.set_cpu()

PI_INTERFACE_VERSION = "v2.5.0"
PI_CLIENT_LANGUAGE = "zh_cn"


def current_time() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def load_settings() -> SettingsModel:
    with open("config/settings.json", "r", encoding="utf-8") as f:
        config_data = json.load(f)
    return SettingsModel(**config_data)


class MaaWorker:
    def __init__(self, message_conn: SimpleQueue, interface):
        Toolkit.init_option("./")
        self.interface: InterfaceModel = interface
        self._interface_base_dir = Path("interface.json").resolve().parent
        self.message_conn = message_conn
        self.tasker = Tasker()
        self.controller = None
        self.controller_type: str | None = None
        self.controller_name: str | None = None
        self.current_resource_name: str | None = None
        self.connected = False
        self.stop_flag = False
        self.running = False
        self._task_lock = threading.Lock()
        self._task_thread: threading.Thread | None = None
        self.last_task_status = "idle"
        self.last_task_error: str | None = None
        self._current_task_name: str | None = None
        self.last_device_config_error: str | None = None
        self.last_resource_config_error: str | None = None
        self.configuration_locked = False
        self._agent_start_lock = threading.Lock()
        self._agent_started_once = False
        self._agent_start_succeeded = False
        self._agent_start_error: str | None = None
        self._pi_env: dict[str, str] | None = None
        self._i18n_text_mapping: dict[str, Any] | None = None
        self.send_log("MAA初始化成功")
        self.agent_process: subprocess.Popen | None = None
        self.agent_processes: list[subprocess.Popen] = []
        self.http_client = httpx.Client(timeout=30)

    def _publish_event(self, event: RealtimeEvent):
        self.message_conn.put(event)
        time.sleep(0.05)

    def _get_agent_configs(self):
        if self.interface.agent is None:
            return []
        if isinstance(self.interface.agent, list):
            return self.interface.agent
        return [self.interface.agent]

    def _load_i18n_mapping(self) -> dict[str, Any]:
        if self._i18n_text_mapping is not None:
            return self._i18n_text_mapping

        self._i18n_text_mapping = {}
        if not self.interface.languages:
            return self._i18n_text_mapping

        language_file = self.interface.languages.get(PI_CLIENT_LANGUAGE)
        if not isinstance(language_file, str) or not language_file.strip():
            return self._i18n_text_mapping

        language_path = (self._interface_base_dir / language_file).resolve()
        try:
            with language_path.open("r", encoding="utf-8") as f:
                mapping = json.load(f)
            if isinstance(mapping, dict):
                self._i18n_text_mapping = mapping
        except Exception as exc:
            self.send_log(f"加载语言映射失败: {exc}")
        return self._i18n_text_mapping

    def _lookup_i18n_text(self, key: str) -> str | None:
        mapping = self._load_i18n_mapping()
        if not mapping:
            return None

        normalized_key = key[1:] if key.startswith("$") else key
        if not normalized_key:
            return None

        current: Any = mapping
        for part in normalized_key.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if isinstance(current, str):
            return current

        flat_value = mapping.get(normalized_key)
        if isinstance(flat_value, str):
            return flat_value
        return None

    def _resolve_i18n_payload(self, payload: Any):
        if isinstance(payload, dict):
            return {
                key: self._resolve_i18n_payload(value) for key, value in payload.items()
            }
        if isinstance(payload, list):
            return [self._resolve_i18n_payload(item) for item in payload]
        if isinstance(payload, str) and payload.startswith("$"):
            translated = self._lookup_i18n_text(payload)
            if translated is not None:
                return translated
        return payload

    def _get_selected_controller_payload(self) -> dict[str, Any]:
        controller = self._get_controller_definition(self.controller_name)
        if controller is None:
            return {}
        payload = controller.model_dump(exclude_none=True, mode="json")
        resolved_payload = self._resolve_i18n_payload(payload)
        if isinstance(resolved_payload, dict):
            return resolved_payload
        return {}

    def _get_selected_resource_payload(self) -> dict[str, Any]:
        resource_definition = self._get_current_resource_definition()
        if resource_definition is None:
            return {}
        payload = resource_definition.model_dump(exclude_none=True, mode="json")
        resolved_payload = self._resolve_i18n_payload(payload)
        if isinstance(resolved_payload, dict):
            return resolved_payload
        return {}

    def is_connection_alive(self) -> bool:
        if not self.connected or self.controller is None:
            return False
        return self.controller.connected

    def reset_connection_state(self, reason: str | None = None):
        state_changed = (
            self.connected
            or self.configuration_locked
            or self.controller is not None
            or self.controller_name is not None
            or self.controller_type is not None
        )
        self.connected = False
        self.configuration_locked = False
        self.controller = None
        self.controller_name = None
        self.controller_type = None
        self.current_resource_name = None

        if reason:
            self.last_device_config_error = reason
            if state_changed:
                self.send_log(reason)

    def _build_pi_env(self) -> dict[str, str]:
        controller_payload = self._get_selected_controller_payload()
        resource_payload = self._get_selected_resource_payload()
        with open("version", "r") as f:
            client_version = f.read().strip()
        return {
            "PI_INTERFACE_VERSION": PI_INTERFACE_VERSION,
            "PI_CLIENT_NAME": "MWU",
            "PI_CLIENT_VERSION": client_version,
            "PI_CLIENT_LANGUAGE": PI_CLIENT_LANGUAGE,
            "PI_CLIENT_MAAFW_VERSION": "v" + metadata.version("maafw"),
            "PI_VERSION": self.interface.version or "",
            "PI_CONTROLLER": json.dumps(
                controller_payload, ensure_ascii=False, separators=(",", ":")
            ),
            "PI_RESOURCE": json.dumps(
                resource_payload, ensure_ascii=False, separators=(",", ":")
            ),
        }

    def _ensure_agent_started_once(self) -> bool:
        if not self._get_agent_configs():
            return True

        if self._agent_started_once:
            return self._agent_start_succeeded

        with self._agent_start_lock:
            if self._agent_started_once:
                return self._agent_start_succeeded

            self._agent_started_once = True
            try:
                self._pi_env = self._build_pi_env()
                self.load_agent(self._pi_env)
                self._agent_start_succeeded = True
                self.send_log("Agent加载完成")
            except Exception as exc:
                self._agent_start_succeeded = False
                self._agent_start_error = str(exc) or "未知错误"
                self.send_log(f"Agent初始化失败: {self._agent_start_error}")

        return self._agent_start_succeeded

    def _show_system_notification(self, title: str, message: str):
        notifier = plyer.notification
        if notifier is None:
            raise RuntimeError("当前平台不支持系统通知")

        notify_func = getattr(notifier, "notify", None)
        if notify_func is None:
            raise RuntimeError("当前平台不支持系统通知")

        notify_func(
            title=title,
            message=message,
            app_name=self.interface.label,
            timeout=30,
        )

    def emit_event(
        self,
        event: RealtimeEventName,
        message: str,
        *,
        level: RealtimeEventLevel = "info",
        notify: bool = False,
        title: str | None = None,
    ):
        realtime_event = RealtimeEvent(
            event=event,
            level=level,
            message=message,
            time=current_time(),
            notify=notify,
            title=title,
        )

        self._publish_event(realtime_event)

        if not notify:
            return

        settings = load_settings()

        if settings.notification.systemNotification:
            try:
                self._show_system_notification(
                    title or self.interface.label or "MWU", message
                )
            except Exception as e:
                self.send_log(f"系统通知发送失败: {e}")

        if settings.notification.externalNotification:
            try:
                template_body = settings.notification.body.strip()
                if template_body:
                    body = json.loads(
                        template_body.replace("{{title}}", title or "").replace(
                            "{{message}}", message
                        )
                    )
                else:
                    body = {"title": title or self.interface.label, "message": message}

                headers = {}
                if settings.notification.headers:
                    headers = json.loads(settings.notification.headers)

                auth = None
                if settings.notification.username and settings.notification.password:
                    auth = (
                        settings.notification.username,
                        settings.notification.password,
                    )

                if settings.notification.method == "POST":
                    if settings.notification.contentType == "application/json":
                        if auth is not None:
                            self.http_client.post(
                                settings.notification.webhook,
                                headers=headers,
                                json=body,
                                auth=auth,
                            )
                        else:
                            self.http_client.post(
                                settings.notification.webhook,
                                headers=headers,
                                json=body,
                            )
                    else:
                        if auth is not None:
                            self.http_client.post(
                                settings.notification.webhook,
                                headers=headers,
                                data=body,
                                auth=auth,
                            )
                        else:
                            self.http_client.post(
                                settings.notification.webhook,
                                headers=headers,
                                data=body,
                            )
                else:
                    self.http_client.get(settings.notification.webhook, params=body)
            except Exception as e:
                self.send_log(f"外部通知发送失败: {e}")

    def send_log(self, msg):
        self.emit_event("log", msg)

    def send_notification(
        self,
        title,
        message,
        *,
        event: RealtimeEventName = "notification.test",
        level: RealtimeEventLevel = "info",
    ):
        self.emit_event(event, message, level=level, notify=True, title=title)

    def _build_task_subject(self, task_list: list[str]) -> str:
        if self._current_task_name:
            return self._current_task_name
        if len(task_list) == 1:
            return task_list[0]
        return f"{len(task_list)} 个任务"

    def _emit_task_started(self, task_list: list[str]):
        self.send_notification(
            "任务开始",
            f"开始执行: {self._build_task_subject(task_list)}",
            event="task.started",
            level="info",
        )

    def _emit_task_completed(self, task_list: list[str]):
        settings = load_settings()
        self.emit_event(
            "task.completed",
            f"{self._build_task_subject(task_list)} 执行完成",
            level="success",
            notify=settings.notification.notifyOnComplete,
            title="任务完成",
        )

    def _emit_task_failed(self, task_list: list[str], error_message: str):
        settings = load_settings()
        self.emit_event(
            "task.failed",
            f"{self._build_task_subject(task_list)} 执行失败，请检查日志",
            level="error",
            notify=settings.notification.notifyOnError,
            title="任务失败",
        )
        self.send_log(f"任务异常详情: {error_message}")

    def _get_controller_definition(self, controller_name: str | None):
        return device_get_controller_definition(self, controller_name)

    def get_device(self, controller_name: str | None = None) -> dict:
        return device_get_device(self, controller_name)

    def connect_device(self, device_config: DeviceModel) -> bool:
        return device_connect_device(self, device_config, resource)

    def set_resource(self, resource_name):
        return device_set_resource(self, resource_name, resource)

    def _deep_merge_pipeline_override(
        self,
        base: PipelineOverride | None,
        override: PipelineOverride | None,
    ) -> PipelineOverride:
        merged: PipelineOverride = copy.deepcopy(base) if base else {}
        if not override:
            return merged

        for key, value in override.items():
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                merged[key] = self._deep_merge_pipeline_override(existing, value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged

    def _get_current_task_definition(self, task_name: str):
        return next(
            (task for task in self.interface.task or [] if task.entry == task_name),
            None,
        )

    def _get_current_resource_definition(self):
        if self.current_resource_name is None:
            return None
        return next(
            (
                item
                for item in self.interface.resource
                if item.name == self.current_resource_name
            ),
            None,
        )

    def _get_active_controller_definitions(self):
        controller = self._get_controller_definition(self.controller_name)
        return [controller] if controller is not None else []

    def _get_active_controller_names(self) -> set[str]:
        return {
            controller.name for controller in self._get_active_controller_definitions()
        }

    def _is_option_active_for_context(self, option, controller_names: set[str]) -> bool:
        if option.controller and not controller_names.intersection(option.controller):
            return False
        if option.resource and (
            self.current_resource_name is None
            or self.current_resource_name not in option.resource
        ):
            return False
        return True

    def _normalize_choice_value(
        self, option_name: str, option, options: dict[str, TaskOptionValue]
    ) -> str:
        assert option.cases is not None
        case_names = [case.name for case in option.cases]
        default_value = (
            option.default_case if isinstance(option.default_case, str) else ""
        )
        if default_value not in case_names:
            default_value = case_names[0] if case_names else ""

        raw_value = options.get(option_name)
        if isinstance(raw_value, str) and raw_value in case_names:
            return raw_value
        return default_value

    def _normalize_checkbox_values(
        self,
        option_name: str,
        option,
        options: dict[str, TaskOptionValue],
    ) -> list[str]:
        assert option.cases is not None
        case_order = [case.name for case in option.cases]
        default_values = (
            option.default_case if isinstance(option.default_case, list) else []
        )
        raw_value = options.get(option_name)

        if raw_value is None:
            selected_values = [
                value for value in default_values if isinstance(value, str)
            ]
        elif isinstance(raw_value, list):
            selected_values = [value for value in raw_value if isinstance(value, str)]
        elif isinstance(raw_value, str):
            try:
                parsed_value = json.loads(raw_value)
            except json.JSONDecodeError:
                parsed_value = [raw_value] if raw_value in case_order else []

            if isinstance(parsed_value, list):
                selected_values = [
                    value for value in parsed_value if isinstance(value, str)
                ]
            else:
                selected_values = []
        else:
            selected_values = []

        selected_set = set(selected_values)
        return [case_name for case_name in case_order if case_name in selected_set]

    def _coerce_input_value(
        self, raw_value: str, pipeline_type: str | None
    ) -> tuple[object, str]:
        if pipeline_type == "bool":
            typed_value = raw_value.lower() in {"true", "1", "yes", "y", "on"}
            return typed_value, "true" if typed_value else "false"
        if pipeline_type == "int":
            typed_value = int(raw_value)
            return typed_value, str(typed_value)
        return raw_value, raw_value

    def _substitute_pipeline_placeholders(
        self,
        value,
        typed_replacements: dict[str, object],
        text_replacements: dict[str, str],
    ):
        if isinstance(value, dict):
            return {
                key: self._substitute_pipeline_placeholders(
                    nested_value,
                    typed_replacements,
                    text_replacements,
                )
                for key, nested_value in value.items()
            }
        if isinstance(value, list):
            return [
                self._substitute_pipeline_placeholders(
                    item,
                    typed_replacements,
                    text_replacements,
                )
                for item in value
            ]
        if isinstance(value, str):
            if value in typed_replacements:
                return copy.deepcopy(typed_replacements[value])

            substituted = value
            for placeholder, replacement in text_replacements.items():
                substituted = substituted.replace(placeholder, replacement)
            return substituted
        return copy.deepcopy(value)

    def _build_input_pipeline_override(
        self,
        option_name: str,
        option,
        options: dict[str, TaskOptionValue],
    ) -> PipelineOverride:
        if not option.pipeline_override or not option.inputs:
            return {}

        typed_replacements: dict[str, object] = {}
        text_replacements: dict[str, str] = {}
        for field in option.inputs:
            raw_value = options.get(f"{option_name}_{field.name}", field.default or "")
            if isinstance(raw_value, list):
                raw_text = raw_value[0] if raw_value else ""
            else:
                raw_text = str(raw_value)

            typed_value, text_value = self._coerce_input_value(
                raw_text,
                field.pipeline_type,
            )
            placeholder = f"{{{field.name}}}"
            typed_replacements[placeholder] = typed_value
            text_replacements[placeholder] = text_value

        return cast(
            PipelineOverride,
            self._substitute_pipeline_placeholders(
                option.pipeline_override,
                typed_replacements,
                text_replacements,
            ),
        )

    def _build_scan_select_pipeline_override(
        self,
        option_name: str,
        option,
        options: dict[str, TaskOptionValue],
    ) -> PipelineOverride:
        if not option.pipeline_override:
            return {}

        if option.cases is None:
            return copy.deepcopy(option.pipeline_override)

        selected_value = self._normalize_choice_value(option_name, option, options)
        placeholder = f"{{{option_name}}}"
        return cast(
            PipelineOverride,
            self._substitute_pipeline_placeholders(
                option.pipeline_override,
                {placeholder: selected_value},
                {placeholder: selected_value},
            ),
        )

    def _build_option_pipeline_override(
        self,
        option_name: str,
        options: dict[str, TaskOptionValue],
        controller_names: set[str],
        lineage: set[str] | None = None,
    ) -> PipelineOverride:
        option_map = self.interface.option or {}
        option = option_map.get(option_name)
        if option is None:
            return {}
        if not self._is_option_active_for_context(option, controller_names):
            return {}

        lineage = lineage or set()
        if option_name in lineage:
            return {}
        next_lineage = {*lineage, option_name}

        merged: PipelineOverride = {}
        if option.type == "input":
            merged = self._deep_merge_pipeline_override(
                merged,
                self._build_input_pipeline_override(option_name, option, options),
            )
            return merged

        if option.type == "scan_select":
            merged = self._deep_merge_pipeline_override(
                merged,
                self._build_scan_select_pipeline_override(
                    option_name,
                    option,
                    options,
                ),
            )
        elif option.pipeline_override:
            merged = self._deep_merge_pipeline_override(
                merged, option.pipeline_override
            )

        if option.type in {"select", "switch"} and option.cases:
            active_case_name = self._normalize_choice_value(
                option_name, option, options
            )
            active_case = next(
                (case for case in option.cases if case.name == active_case_name),
                None,
            )
            if active_case and active_case.pipeline_override:
                merged = self._deep_merge_pipeline_override(
                    merged,
                    active_case.pipeline_override,
                )
            if active_case and active_case.option:
                merged = self._deep_merge_pipeline_override(
                    merged,
                    self._build_option_group_pipeline_override(
                        active_case.option,
                        options,
                        controller_names,
                        next_lineage,
                    ),
                )
            return merged

        if option.type == "checkbox" and option.cases:
            selected_case_names = set(
                self._normalize_checkbox_values(option_name, option, options)
            )
            for case in option.cases:
                if case.name not in selected_case_names:
                    continue
                if case.pipeline_override:
                    merged = self._deep_merge_pipeline_override(
                        merged,
                        case.pipeline_override,
                    )
                if case.option:
                    merged = self._deep_merge_pipeline_override(
                        merged,
                        self._build_option_group_pipeline_override(
                            case.option,
                            options,
                            controller_names,
                            next_lineage,
                        ),
                    )
            return merged

        return merged

    def _build_option_group_pipeline_override(
        self,
        option_names: list[str],
        options: dict[str, TaskOptionValue],
        controller_names: set[str],
        lineage: set[str] | None = None,
    ) -> PipelineOverride:
        merged: PipelineOverride = {}
        for option_name in option_names:
            merged = self._deep_merge_pipeline_override(
                merged,
                self._build_option_pipeline_override(
                    option_name,
                    options,
                    controller_names,
                    lineage,
                ),
            )
        return merged

    def _build_task_pipeline_override(
        self,
        task_name: str,
        options: dict[str, TaskOptionValue],
    ) -> PipelineOverride:
        task_definition = self._get_current_task_definition(task_name)
        if task_definition is None:
            return {}

        controller_names = self._get_active_controller_names()
        resource_definition = self._get_current_resource_definition()
        controller_option_names: list[str] = []
        for controller in self._get_active_controller_definitions():
            if controller.option:
                controller_option_names.extend(controller.option)

        merged = copy.deepcopy(task_definition.pipeline_override) or {}
        for option_names in [
            self.interface.global_option or [],
            resource_definition.option
            if resource_definition and resource_definition.option
            else [],
            controller_option_names,
            task_definition.option or [],
        ]:
            merged = self._deep_merge_pipeline_override(
                merged,
                self._build_option_group_pipeline_override(
                    option_names,
                    options,
                    controller_names,
                ),
            )
        return merged

    def black_magic(self, agent_config):
        run_black_magic(agent_config, resource)

    def load_agent(self, pi_env: dict[str, str] | None = None):
        self.agent_process, self.agent_processes = load_agents(
            self._get_agent_configs(),
            resource,
            self.send_log,
            pi_env=pi_env,
        )

    def start_task(
        self,
        task_list,
        options: dict[str, TaskOptionValue],
        task_name: str | None = None,
    ) -> bool:
        if not self.connected:
            return False
        if not self.current_resource_name:
            self.last_resource_config_error = "请先设置资源"
            self.send_log(self.last_resource_config_error)
            return False
        if not self._ensure_agent_started_once():
            return False

        cleaned_options: dict[str, TaskOptionValue] = {}
        for key, value in options.items():
            if value is None:
                cleaned_options[key] = ""
            else:
                cleaned_options[key] = value
        return start_worker_task(self, task_list, cleaned_options, task_name)

    def stop_task(self) -> bool:
        return stop_worker_task(self)

    def _run_process(self, task_list, options: dict[str, TaskOptionValue]):
        run_task_process(self, task_list, options)

    def get_screencap_bytes(self):
        if not self.connected or not self.controller:
            return None
        try:
            image = self.controller.post_screencap().wait().get()
            if image is not None:
                image_pil = Image.fromarray(image[:, :, ::-1])
                img_byte_arr = io.BytesIO()
                image_pil.save(img_byte_arr, format="JPEG")
                return img_byte_arr.getvalue()
        except Exception:
            self.reset_connection_state("检测到设备连接已断开，已解除设备与资源锁定")
        return None
