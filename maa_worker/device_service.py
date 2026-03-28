from __future__ import annotations

import os
import re
import sys
import time
from typing import TYPE_CHECKING, Any

from maa.controller import (
    AdbController,
    GamepadController,
    PlayCoverController,
    Win32Controller,
)
from maa.toolkit import Toolkit

from models.api import DeviceModel

if TYPE_CHECKING:
    from maa_utils import MaaWorker


def is_controller_supported(controller) -> tuple[bool, str]:
    match controller.type:
        case "Adb":
            return True, ""
        case "Win32":
            if sys.platform != "win32":
                return False, "platform_not_supported"
            if not controller.win32:
                return False, "controller_config_missing"
            return True, ""
        case "PlayCover":
            if sys.platform != "darwin":
                return False, "platform_not_supported"
            return True, ""
        case "Gamepad":
            if sys.platform != "win32":
                return False, "platform_not_supported"
            if not controller.gamepad:
                return False, "controller_config_missing"
            return True, ""
        case _:
            return False, "controller_not_supported"


class DeviceService:
    def __init__(self, worker: "MaaWorker"):
        self.worker = worker

    def _load_resource_bundle(self, path: str) -> str:
        resolved_path = os.path.realpath(path.replace("{PROJECT_DIR}", os.getcwd()))
        self.worker.resource.post_bundle(resolved_path).wait()
        return resolved_path

    def _append_controller_resource_paths(self, controller) -> list[str]:
        loaded_paths: list[str] = []
        if controller is None or not controller.attach_resource_path:
            return loaded_paths

        for path in controller.attach_resource_path:
            loaded_paths.append(self._load_resource_bundle(path))
        return loaded_paths

    def _build_controller_display_labels(self) -> dict[str, str]:
        label_counts: dict[str, int] = {}
        base_labels: dict[str, str] = {}

        for controller in self.worker.interface.controller:
            base_label = controller.label or controller.name or controller.type
            base_labels[controller.name] = base_label
            label_counts[base_label] = label_counts.get(base_label, 0) + 1

        display_labels: dict[str, str] = {}
        for controller in self.worker.interface.controller:
            base_label = base_labels[controller.name]
            if label_counts[base_label] > 1:
                display_labels[controller.name] = f"{base_label}({controller.name})"
            else:
                display_labels[controller.name] = base_label
        return display_labels

    def get_controller_definition(self, controller_name: str | None):
        if not controller_name:
            return None
        return next(
            (
                controller
                for controller in self.worker.interface.controller
                if controller.name == controller_name
            ),
            None,
        )

    def get_current_resource_definition(self):
        resource_name = self.worker.device_state.current_resource_name
        if resource_name is None:
            return None
        return next(
            (
                item
                for item in self.worker.interface.resource
                if item.name == resource_name
            ),
            None,
        )

    def get_active_controller_definitions(self) -> list[Any]:
        controller = self.get_controller_definition(
            self.worker.device_state.controller_name
        )
        return [controller] if controller is not None else []

    def get_active_controller_names(self) -> set[str]:
        return {
            controller.name for controller in self.get_active_controller_definitions()
        }

    def build_device_capabilities(self) -> list[dict[str, Any]]:
        capabilities: list[dict[str, Any]] = []
        display_labels = self._build_controller_display_labels()
        for controller in self.worker.interface.controller:
            supported, reason = is_controller_supported(controller)
            capabilities.append(
                {
                    "name": controller.name,
                    "type": controller.type,
                    "label": controller.label or controller.name or controller.type,
                    "display_label": display_labels[controller.name],
                    "enabled": supported,
                    "reason": "" if supported else reason,
                    "search_mode": "input"
                    if controller.type == "PlayCover"
                    else "select",
                    "default_address": "127.0.0.1:1717"
                    if controller.type == "PlayCover"
                    else "",
                }
            )

        controller_order = ["Adb", "Win32", "Gamepad", "PlayCover"]
        return sorted(
            capabilities,
            key=lambda item: (
                controller_order.index(item["type"])
                if item["type"] in controller_order
                else len(controller_order),
                item["display_label"],
            ),
        )

    def _find_devices_for_controller(self, controller) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        win32_seen: set[int] = set()
        gamepad_seen: set[int] = set()

        supported, _ = is_controller_supported(controller)
        if not supported:
            return devices

        match controller.type:
            case "Adb":
                for device in Toolkit.find_adb_devices():
                    data = {
                        "name": device.name,
                        "type": "Adb",
                        "adb_path": device.adb_path,
                        "address": device.address,
                        "screencap_methods": str(device.screencap_methods),
                        "input_methods": str(device.input_methods),
                        "config": device.config,
                    }
                    if data not in devices:
                        devices.append(data)
            case "Win32":
                assert controller.win32 is not None
                for device in Toolkit.find_desktop_windows():
                    class_name = device.class_name
                    window_name = device.window_name
                    class_match = not controller.win32.class_regex or re.search(
                        controller.win32.class_regex, class_name
                    )
                    window_match = not controller.win32.window_regex or re.search(
                        controller.win32.window_regex, window_name
                    )
                    if not (class_match and window_match):
                        continue

                    hwnd = int(device.hwnd)
                    if hwnd in win32_seen:
                        continue
                    win32_seen.add(hwnd)

                    devices.append(
                        {
                            "type": "Win32",
                            "hWnd": hwnd,
                            "class_name": class_name,
                            "window_name": window_name,
                            "screencap_methods": controller.win32.screencap or 1,
                            "input_methods": controller.win32.mouse
                            or controller.win32.keyboard
                            or 1,
                        }
                    )
            case "PlayCover":
                return devices
            case "Gamepad":
                assert controller.gamepad is not None
                for device in Toolkit.find_desktop_windows():
                    class_name = device.class_name
                    window_name = device.window_name
                    class_match = not controller.gamepad.class_regex or re.search(
                        controller.gamepad.class_regex, class_name
                    )
                    window_match = not controller.gamepad.window_regex or re.search(
                        controller.gamepad.window_regex, window_name
                    )
                    if not (class_match and window_match):
                        continue

                    hwnd = int(device.hwnd)
                    if hwnd in gamepad_seen:
                        continue
                    gamepad_seen.add(hwnd)

                    devices.append(
                        {
                            "type": "Gamepad",
                            "hWnd": hwnd,
                            "class_name": class_name,
                            "window_name": window_name,
                            "screencap_methods": controller.gamepad.screencap or 1,
                            "gamepad_type": controller.gamepad.gamepad_type or 0,
                        }
                    )
        return devices

    def get_device(self, controller_name: str | None = None) -> dict[str, Any]:
        capabilities = self.build_device_capabilities()
        all_names = [item["name"] for item in capabilities]
        enabled_names = [item["name"] for item in capabilities if item["enabled"]]

        selected_name = controller_name if controller_name in all_names else None
        if not selected_name:
            if enabled_names:
                selected_name = enabled_names[0]
            elif all_names:
                selected_name = all_names[0]

        selected_capability = next(
            (item for item in capabilities if item["name"] == selected_name), None
        )
        devices: list[dict[str, Any]] = []
        if (
            selected_name
            and selected_capability
            and selected_capability["enabled"]
            and selected_capability["search_mode"] == "select"
        ):
            controller = self.get_controller_definition(selected_name)
            if controller is not None:
                devices = self._find_devices_for_controller(controller)

        return {
            "controllers": capabilities,
            "selected_controller": selected_name,
            "devices": devices,
        }

    def is_connection_alive(self) -> bool:
        controller = self.worker.device_state.controller
        if not self.worker.device_state.connected or controller is None:
            return False
        return bool(getattr(controller, "connected", False))

    def reset_connection_state(self, reason: str | None = None):
        state = self.worker.device_state
        state_changed = (
            state.connected
            or state.configuration_locked
            or state.controller is not None
            or state.controller_name is not None
            or state.controller_type is not None
        )
        state.connected = False
        state.configuration_locked = False
        state.controller = None
        state.controller_name = None
        state.controller_type = None
        state.current_resource_name = None

        if reason:
            state.last_device_error = reason
            if state_changed:
                self.worker.events.send_log(reason)

    def connect(self, device_config: DeviceModel) -> bool:
        state = self.worker.device_state
        if state.configuration_locked:
            if not self.is_connection_alive():
                self.reset_connection_state(
                    "检测到设备连接已断开，已解除设备与资源锁定"
                )
            else:
                state.last_device_error = (
                    "设备与资源已锁定，当前生命周期内不允许重新连接"
                )
                self.worker.events.send_log(state.last_device_error)
                return False

        state.last_device_error = None
        device_type = device_config.type
        selected_controller = self.get_controller_definition(
            device_config.controller_name
        )
        if selected_controller is None or selected_controller.type != device_type:
            state.last_device_error = "未找到匹配的控制器配置"
            self.worker.events.send_log(state.last_device_error)
            return False

        status = False
        controller = None
        match device_type:
            case "Adb":
                controller = AdbController(
                    adb_path=device_config.adb_path,
                    address=device_config.address,
                    screencap_methods=int(device_config.screencap_methods or 0),
                    input_methods=int(device_config.input_methods or 0),
                    config=device_config.config or {},
                )
                status = controller.post_connection().wait().succeeded
            case "Win32":
                controller = Win32Controller(
                    hWnd=device_config.hWnd,
                    screencap_method=int(device_config.screencap_methods or 0),
                    mouse_method=int(device_config.input_methods or 0),
                    keyboard_method=int(device_config.input_methods or 0),
                )
                status = controller.post_connection().wait().succeeded
            case "Gamepad":
                controller = GamepadController(
                    hWnd=device_config.hWnd,
                    gamepad_type=int(device_config.gamepad_type or 0),
                    screencap_method=int(device_config.screencap_methods or 0),
                )
                status = controller.post_connection().wait().succeeded
            case "PlayCover":
                controller = PlayCoverController(
                    address=device_config.address or "127.0.0.1:1717",
                    uuid=device_config.uuid,
                )
                status = controller.post_connection().wait().succeeded

        conn_fail_msg = "设备连接失败，请检查终端日志"
        if not status:
            self.worker.events.show_system_notification(
                self.worker.interface.title or self.worker.interface.label or "MWU",
                conn_fail_msg,
            )
            state.last_device_error = conn_fail_msg
            self.worker.events.send_log(state.last_device_error)
            return False

        time.sleep(1)
        if self.worker.tasker.bind(self.worker.resource, controller):
            state.connected = True
            state.controller = controller
            state.controller_type = device_type
            state.controller_name = selected_controller.name
            state.last_device_error = None
            self.worker.events.send_log("设备连接成功")
            return True

        self.worker.events.show_system_notification(
            self.worker.interface.title or self.worker.interface.label or "MWU",
            conn_fail_msg,
        )
        state.last_device_error = conn_fail_msg
        self.worker.events.send_log(state.last_device_error)
        return False

    def set_resource(self, resource_name: str) -> bool:
        state = self.worker.device_state
        if state.configuration_locked:
            if not self.is_connection_alive():
                self.reset_connection_state(
                    "检测到设备连接已断开，已解除设备与资源锁定"
                )
            else:
                state.last_resource_error = (
                    "设备与资源已锁定，当前生命周期内不允许修改资源"
                )
                self.worker.events.send_log(state.last_resource_error)
                return False

        state.last_resource_error = None
        for resource_config in self.worker.interface.resource:
            if resource_config.name != resource_name:
                continue

            loaded_paths = [
                self._load_resource_bundle(path) for path in resource_config.path
            ]
            state.current_resource_name = resource_config.name
            controller = self.get_controller_definition(state.controller_name)
            attached_paths = self._append_controller_resource_paths(controller)
            if loaded_paths:
                self.worker.events.send_log(
                    f"资源主路径已加载: {', '.join(loaded_paths)}"
                )
            if attached_paths:
                controller_label = (
                    (controller.label or controller.name) if controller else ""
                )
                self.worker.events.send_log(
                    f"已为控制器 {controller_label} 加载附加资源: {', '.join(attached_paths)}"
                )
            self.worker.events.send_log(f"资源已设置为: {resource_config.name}")
            if state.connected:
                state.configuration_locked = True
            return True

        state.last_resource_error = f"未找到资源: {resource_name}"
        self.worker.events.send_log(state.last_resource_error)
        return False
