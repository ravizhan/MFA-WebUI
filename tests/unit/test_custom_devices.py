"""Tests for custom device persistence and scan+custom merge in DeviceService."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app_state import WorkerContext
from maa_worker.device_service import (
    DeviceService,
    canonicalize_custom_address,
    custom_record_to_device,
)
from models.api import CustomDeviceCreate


def _controller(name: str, type_: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, type=type_, label=name, win32=None, gamepad=None)


class _FakeWorker:
    def __init__(self, base_dir: Path, controllers: list[Any] | None = None):
        self.state = SimpleNamespace(context=WorkerContext(interface_base_dir=base_dir))
        self.interface = SimpleNamespace(
            controller=controllers
            or [
                _controller("AdbController", "Adb"),
                _controller("Win32Controller", "Win32"),
                _controller("GamepadController", "Gamepad"),
                _controller("PlayCoverController", "PlayCover"),
            ]
        )


@pytest.fixture
def app_root(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    root.mkdir()
    return root


@pytest.fixture
def service(app_root: Path) -> DeviceService:
    return DeviceService(_FakeWorker(app_root))  # type: ignore[arg-type]


class TestCustomDeviceCreateModel:
    def test_trims_and_rejects_empty(self):
        payload = CustomDeviceCreate(
            controller_name="  AdbController  ",
            type="Adb",
            address="  127.0.0.1:5555  ",
        )
        assert payload.controller_name == "AdbController"
        assert payload.address == "127.0.0.1:5555"
        with pytest.raises(ValidationError):
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="   ",
            )


class TestCanonicalizeCustomAddress:
    def test_adb_and_playcover_trim(self):
        assert canonicalize_custom_address("Adb", "  1.2.3.4:5555  ") == "1.2.3.4:5555"
        assert (
            canonicalize_custom_address("PlayCover", " 127.0.0.1:1717 ")
            == "127.0.0.1:1717"
        )
        with pytest.raises(ValueError):
            canonicalize_custom_address("Adb", "  ")

    def test_win32_canonical_and_reject(self):
        assert canonicalize_custom_address("Win32", "00123") == "123"
        for bad in ("0", "-1", "abc"):
            with pytest.raises(ValueError):
                canonicalize_custom_address("Win32", bad)

    def test_gamepad_canonical_and_reject(self):
        assert canonicalize_custom_address("Gamepad", "0042|01") == "42|1"
        for bad in ("0|0", "42|2", "42", "abc|0"):
            with pytest.raises(ValueError):
                canonicalize_custom_address("Gamepad", bad)


class TestCustomRecordToDevice:
    def test_type_mappings(self):
        adb = custom_record_to_device(
            {
                "controller_name": "AdbController",
                "type": "Adb",
                "address": "10.0.0.1:5555",
            }
        )
        assert adb == {
            "name": "",
            "type": "Adb",
            "adb_path": "",
            "address": "10.0.0.1:5555",
            "screencap_methods": 0,
            "input_methods": 0,
            "config": {},
        }

        win32 = custom_record_to_device(
            {"controller_name": "Win32Controller", "type": "Win32", "address": "123456"}
        )
        assert win32["hWnd"] == 123456

        gamepad = custom_record_to_device(
            {
                "controller_name": "GamepadController",
                "type": "Gamepad",
                "address": "42|1",
            }
        )
        assert gamepad["hWnd"] == 42
        assert gamepad["gamepad_type"] == 1

        playcover = custom_record_to_device(
            {
                "controller_name": "PlayCoverController",
                "type": "PlayCover",
                "address": "127.0.0.1:1717",
            }
        )
        assert playcover == {"type": "PlayCover", "address": "127.0.0.1:1717"}


class TestCustomDevicePersistence:
    def _write_settings(
        self,
        app_root: Path,
        custom_devices: list[dict[str, object]] | None = None,
    ) -> Path:
        path = app_root / "config" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {"panel": {}}
        if custom_devices is not None:
            data["panel"] = {"customDevices": custom_devices}  # type: ignore[dict-item]
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_persists_across_service_instances(self, app_root: Path):
        svc1 = DeviceService(_FakeWorker(app_root))  # type: ignore[arg-type]
        saved = svc1.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="192.168.1.10:5555",
            )
        )
        assert saved["address"] == "192.168.1.10:5555"
        assert (app_root / "config" / "settings.json").exists()

        svc2 = DeviceService(_FakeWorker(app_root))  # type: ignore[arg-type]
        assert svc2._load_custom_devices() == [
            {
                "controller_name": "AdbController",
                "type": "Adb",
                "address": "192.168.1.10:5555",
            }
        ]

    def test_dedupes_by_canonical_identity(self, service: DeviceService):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="  10.0.0.2:5555  ",
            )
        )
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="10.0.0.2:5555",
            )
        )
        assert len(service._load_custom_devices()) == 1

        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="Win32Controller",
                type="Win32",
                address="00100",
            )
        )
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="Win32Controller",
                type="Win32",
                address="100",
            )
        )
        records = service._load_custom_devices()
        win32 = [r for r in records if r["type"] == "Win32"]
        assert len(win32) == 1
        assert win32[0]["address"] == "100"

    def test_rejects_invalid_controller_and_address(self, service: DeviceService):
        with pytest.raises(ValueError, match="正整数"):
            service.add_custom_device(
                CustomDeviceCreate(
                    controller_name="Win32Controller",
                    type="Win32",
                    address="0",
                )
            )
        with pytest.raises(ValueError, match="未找到匹配的控制器配置"):
            service.add_custom_device(
                CustomDeviceCreate(
                    controller_name="Missing",
                    type="Adb",
                    address="1.1.1.1:5555",
                )
            )
        with pytest.raises(ValueError, match="控制器类型不匹配"):
            service.add_custom_device(
                CustomDeviceCreate(
                    controller_name="AdbController",
                    type="Win32",
                    address="12345",
                )
            )

    def test_tolerates_corrupt_settings_and_skips_invalid(
        self, service: DeviceService, app_root: Path
    ):
        path = app_root / "config" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")
        assert service._load_custom_devices() == []

        self._write_settings(
            app_root,
            [
                {
                    "controller_name": "Win32Controller",
                    "type": "Win32",
                    "address": "0",
                },
                {
                    "controller_name": "AdbController",
                    "type": "Adb",
                    "address": "10.0.0.9:5555",
                },
                {
                    "controller_name": "Win32Controller",
                    "type": "Win32",
                    "address": "00123",
                },
            ],
        )
        assert service._load_custom_devices() == [
            {
                "controller_name": "AdbController",
                "type": "Adb",
                "address": "10.0.0.9:5555",
            },
            {
                "controller_name": "Win32Controller",
                "type": "Win32",
                "address": "123",
            },
        ]

    def test_path_uses_interface_base_dir_not_cwd(
        self, app_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        other_cwd = tmp_path / "other_cwd"
        other_cwd.mkdir()
        monkeypatch.chdir(other_cwd)

        svc = DeviceService(_FakeWorker(app_root))  # type: ignore[arg-type]
        svc.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="8.8.8.8:5555",
            )
        )
        assert (app_root / "config" / "settings.json").exists()
        assert not (other_cwd / "config" / "settings.json").exists()


class TestScanCustomMerge:
    def test_merge_appends_custom_only(self, service: DeviceService):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="10.0.0.5:5555",
            )
        )
        scanned = [
            {
                "name": "Phone",
                "type": "Adb",
                "adb_path": "/usr/bin/adb",
                "address": "10.0.0.1:5555",
                "screencap_methods": "1",
                "input_methods": "2",
                "config": {"k": "v"},
            }
        ]
        merged = service._merge_custom_devices("AdbController", scanned)
        assert len(merged) == 2
        assert merged[0]["address"] == "10.0.0.1:5555"
        assert merged[1]["address"] == "10.0.0.5:5555"
        assert merged[1]["name"] == ""

    def test_scan_wins_on_duplicate_identity(self, service: DeviceService):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="10.0.0.1:5555",
            )
        )
        scanned = [
            {
                "name": "RichScan",
                "type": "Adb",
                "adb_path": "C:/adb.exe",
                "address": "10.0.0.1:5555",
                "screencap_methods": "99",
                "input_methods": "88",
                "config": {"from": "scan"},
            }
        ]
        merged = service._merge_custom_devices("AdbController", scanned)
        assert len(merged) == 1
        assert merged[0]["name"] == "RichScan"
        assert merged[0]["adb_path"] == "C:/adb.exe"

    def test_win32_scan_wins_canonical(self, service: DeviceService):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="Win32Controller",
                type="Win32",
                address="00100",
            )
        )
        scanned = [
            {
                "type": "Win32",
                "hWnd": 100,
                "class_name": "Chrome",
                "window_name": "Browser",
                "screencap_methods": 1,
                "input_methods": 1,
            }
        ]
        merged = service._merge_custom_devices("Win32Controller", scanned)
        assert len(merged) == 1
        assert merged[0]["class_name"] == "Chrome"

    def test_get_device_scan_then_merge(self, service: DeviceService):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="custom.only:5555",
            )
        )
        scanned = [
            {
                "name": "Emulator",
                "type": "Adb",
                "adb_path": "adb",
                "address": "127.0.0.1:5555",
                "screencap_methods": "1",
                "input_methods": "1",
                "config": {},
            }
        ]
        with patch.object(
            DeviceService, "_find_devices_for_controller", return_value=scanned
        ):
            data = service.get_device("AdbController")

        addresses = [d.get("address") for d in data["devices"]]
        assert "127.0.0.1:5555" in addresses
        assert "custom.only:5555" in addresses
        assert data["selected_controller"] == "AdbController"
