"""Tests for custom device persistence and scan+custom merge in DeviceService."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from maa_worker.device_service import (
    DeviceService,
    custom_record_to_device,
)
from models.device_address import canonicalize_custom_device_address
from app_state import WorkerContext
from models.api import CustomDeviceCreate


def _controller(name: str, type_: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, type=type_, label=name, win32=None, gamepad=None)


class _FakeWorker:
    def __init__(self, base_dir: Path, controllers: list[Any] | None = None):
        self.context = WorkerContext(interface_base_dir=base_dir)
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
    def test_trims_fields(self):
        payload = CustomDeviceCreate(
            controller_name="  AdbController  ",
            type="Adb",
            address="  127.0.0.1:5555  ",
        )
        assert payload.controller_name == "AdbController"
        assert payload.address == "127.0.0.1:5555"

    def test_rejects_empty_address(self):
        with pytest.raises(ValidationError):
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="   ",
            )

    def test_rejects_empty_controller_name(self):
        with pytest.raises(ValidationError):
            CustomDeviceCreate(controller_name="", type="Adb", address="1.2.3.4:5555")


class TestCanonicalizeCustomAddress:
    def test_adb_and_playcover_trim(self):
        assert (
            canonicalize_custom_device_address("Adb", "  1.2.3.4:5555  ")
            == "1.2.3.4:5555"
        )
        assert (
            canonicalize_custom_device_address("PlayCover", " 127.0.0.1:1717 ")
            == "127.0.0.1:1717"
        )

    def test_adb_empty_rejected(self):
        with pytest.raises(ValueError):
            canonicalize_custom_device_address("Adb", "  ")

    def test_win32_positive_decimal_canonical(self):
        assert canonicalize_custom_device_address("Win32", "00123") == "123"
        assert canonicalize_custom_device_address("Win32", " 42 ") == "42"

    def test_win32_zero_negative_malformed_rejected(self):
        for bad in ("0", "-1", "abc", "12.3", "1e2", ""):
            with pytest.raises(ValueError):
                canonicalize_custom_device_address("Win32", bad)

    def test_gamepad_positive_hwnd_type_0_or_1(self):
        assert canonicalize_custom_device_address("Gamepad", "0042|01") == "42|1"
        assert canonicalize_custom_device_address("Gamepad", " 7 | 0 ") == "7|0"

    def test_gamepad_malformed_zero_negative_rejected(self):
        for bad in (
            "0|0",
            "-1|0",
            "42|2",
            "42|-1",
            "42",
            "42|0|1",
            "abc|0",
            "42|x",
            "",
        ):
            with pytest.raises(ValueError):
                canonicalize_custom_device_address("Gamepad", bad)


class TestCustomRecordToDevice:
    def test_adb_shape(self):
        device = custom_record_to_device(
            {
                "controller_name": "AdbController",
                "type": "Adb",
                "address": "10.0.0.1:5555",
            }
        )
        assert device == {
            "name": "",
            "type": "Adb",
            "adb_path": "",
            "address": "10.0.0.1:5555",
            "screencap_methods": 0,
            "input_methods": 0,
            "config": {},
        }

    def test_win32_parses_hwnd(self):
        device = custom_record_to_device(
            {"controller_name": "Win32Controller", "type": "Win32", "address": "123456"}
        )
        assert device["hWnd"] == 123456
        assert device["class_name"] == ""
        assert device["window_name"] == ""

    def test_gamepad_parses_hwnd_and_type(self):
        device = custom_record_to_device(
            {
                "controller_name": "GamepadController",
                "type": "Gamepad",
                "address": "42|1",
            }
        )
        assert device["hWnd"] == 42
        assert device["gamepad_type"] == 1

    def test_playcover_address(self):
        device = custom_record_to_device(
            {
                "controller_name": "PlayCoverController",
                "type": "PlayCover",
                "address": "127.0.0.1:1717",
            }
        )
        assert device == {"type": "PlayCover", "address": "127.0.0.1:1717"}


class TestCustomDevicePersistence:
    def test_persists_across_service_instances(self, app_root: Path):
        svc1 = DeviceService(_FakeWorker(app_root))  # type: ignore[arg-type]
        payload = CustomDeviceCreate(
            controller_name="AdbController",
            type="Adb",
            address="192.168.1.10:5555",
        )
        saved = svc1.add_custom_device(payload)
        assert saved["address"] == "192.168.1.10:5555"

        path = app_root / "config" / "settings.json"
        assert path.exists()

        svc2 = DeviceService(_FakeWorker(app_root))  # type: ignore[arg-type]
        records = svc2._load_custom_devices()
        assert records == [
            {
                "controller_name": "AdbController",
                "type": "Adb",
                "address": "192.168.1.10:5555",
            }
        ]

    def test_dedupes_by_identity(self, service: DeviceService):
        payload = CustomDeviceCreate(
            controller_name="AdbController",
            type="Adb",
            address="  10.0.0.2:5555  ",
        )
        service.add_custom_device(payload)
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="10.0.0.2:5555",
            )
        )
        assert len(service._load_custom_devices()) == 1

    def test_win32_canonical_dedup(self, service: DeviceService):
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
        assert len(records) == 1
        assert records[0]["address"] == "100"

    def test_gamepad_canonical_dedup(self, service: DeviceService):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="GamepadController",
                type="Gamepad",
                address="008|01",
            )
        )
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="GamepadController",
                type="Gamepad",
                address="8|1",
            )
        )
        records = service._load_custom_devices()
        assert len(records) == 1
        assert records[0]["address"] == "8|1"

    def test_rejects_zero_win32(self, service: DeviceService):
        with pytest.raises(ValueError, match="positive integer"):
            service.add_custom_device(
                CustomDeviceCreate(
                    controller_name="Win32Controller",
                    type="Win32",
                    address="0",
                )
            )

    def test_rejects_malformed_gamepad(self, service: DeviceService):
        with pytest.raises(ValueError):
            service.add_custom_device(
                CustomDeviceCreate(
                    controller_name="GamepadController",
                    type="Gamepad",
                    address="42|9",
                )
            )

    def test_rejects_unknown_controller(self, service: DeviceService):
        with pytest.raises(ValueError, match="未找到匹配的控制器配置"):
            service.add_custom_device(
                CustomDeviceCreate(
                    controller_name="Missing",
                    type="Adb",
                    address="1.1.1.1:5555",
                )
            )

    def test_rejects_type_mismatch(self, service: DeviceService):
        with pytest.raises(ValueError, match="控制器类型不匹配"):
            service.add_custom_device(
                CustomDeviceCreate(
                    controller_name="AdbController",
                    type="Win32",
                    address="12345",
                )
            )

    def _write_settings(
        self,
        app_root: Path,
        custom_devices: list[dict[str, object]] | None = None,
    ) -> Path:
        """Write a minimal settings.json with optional customDevices."""
        path = app_root / "config" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {"panel": {}}
        if custom_devices is not None:
            data["panel"] = {"customDevices": custom_devices}  # type: ignore[dict-item]
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_empty_file_tolerated(self, service: DeviceService, app_root: Path):
        path = app_root / "config" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        assert service._load_custom_devices() == []

    def test_corrupt_file_tolerated(self, service: DeviceService, app_root: Path):
        path = app_root / "config" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")
        assert service._load_custom_devices() == []

    def test_non_list_file_tolerated(self, service: DeviceService, app_root: Path):
        path = app_root / "config" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"oops": true}', encoding="utf-8")
        assert service._load_custom_devices() == []

    def test_skips_invalid_loaded_entries(self, service: DeviceService, app_root: Path):
        self._write_settings(
            app_root,
            [
                {
                    "controller_name": "Win32Controller",
                    "type": "Win32",
                    "address": "0",
                },
                {
                    "controller_name": "Win32Controller",
                    "type": "Win32",
                    "address": "-5",
                },
                {
                    "controller_name": "GamepadController",
                    "type": "Gamepad",
                    "address": "1|9",
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
        records = service._load_custom_devices()
        assert records == [
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

    def test_atomic_save_no_temp_left(self, service: DeviceService, app_root: Path):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="1.1.1.1:5555",
            )
        )
        config_dir = app_root / "config"
        assert (config_dir / "settings.json").exists()
        temps = list(config_dir.glob(".settings.json.*.tmp"))
        assert temps == []

    def test_concurrent_adds_dedupe_and_valid_json(
        self, service: DeviceService, app_root: Path
    ):
        def add_one(i: int) -> None:
            # Even indices share one canonical Win32 address; odds unique Adb.
            if i % 2 == 0:
                service.add_custom_device(
                    CustomDeviceCreate(
                        controller_name="Win32Controller",
                        type="Win32",
                        address=f"00{100 + (i % 4)}",
                    )
                )
            else:
                service.add_custom_device(
                    CustomDeviceCreate(
                        controller_name="AdbController",
                        type="Adb",
                        address=f"10.0.0.{i}:5555",
                    )
                )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(add_one, range(20)))

        path = app_root / "config" / "settings.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        custom_list = data.get("panel", {}).get("customDevices", [])
        assert isinstance(custom_list, list)
        # File must always be valid complete JSON (atomic replace).
        records = service._load_custom_devices()
        identities = {(r["controller_name"], r["type"], r["address"]) for r in records}
        assert len(identities) == len(records)

        # Concurrent readers never see truncated content.
        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(30):
                    loaded = service._load_custom_devices()
                    assert isinstance(loaded, list)
            except Exception as exc:  # pragma: no cover - fail collection
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="9.9.9.9:5555",
            )
        )
        for t in threads:
            t.join()
        assert errors == []


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
        assert merged[1]["adb_path"] == ""

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
        assert merged[0]["screencap_methods"] == "99"
        assert merged[0]["config"] == {"from": "scan"}

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
                address="10.99.99.1:5555",
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
        assert "10.99.99.1:5555" in addresses
        assert data["selected_controller"] == "AdbController"
