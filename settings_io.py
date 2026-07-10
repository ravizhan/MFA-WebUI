from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

import json_utils as json
from models.settings import SettingsModel

SETTINGS_LOCK = threading.RLock()


def default_settings_path() -> Path:
    """Return config/settings.json under the frozen or source app root."""
    if getattr(sys, "frozen", False):
        app_root = Path(sys.executable).resolve().parent
    else:
        app_root = Path(__file__).resolve().parent
    return app_root / "config" / "settings.json"


def read_settings_raw(path: Path) -> dict[str, Any]:
    """Read settings.json under lock. Corrupt or missing files yield {}."""
    with SETTINGS_LOCK:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        return raw


def atomic_write_settings(path: Path, data: dict[str, Any]) -> None:
    """Atomically write settings.json under lock (tmp + fsync + os.replace)."""
    with SETTINGS_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".settings.json.{os.getpid()}.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise


def load_settings_model(path: Path, **validate_kwargs: Any) -> SettingsModel:
    """Load and validate settings from path. Missing/corrupt → defaults."""
    raw = read_settings_raw(path)
    try:
        return SettingsModel.model_validate(raw, **validate_kwargs)
    except Exception:
        return SettingsModel()


def write_settings_preserving_custom_devices(
    path: Path, settings: SettingsModel
) -> dict[str, Any]:
    """Write settings while force-preserving panel.customDevices from disk.

    Frontend POST /api/settings must not wipe custom devices saved by the
    device service. Returns the final dict written to disk.
    """
    with SETTINGS_LOCK:
        payload = settings.model_dump()
        disk = read_settings_raw(path)
        disk_panel = disk.get("panel") if isinstance(disk, dict) else None
        if isinstance(disk_panel, dict) and "customDevices" in disk_panel:
            panel = payload.get("panel")
            if not isinstance(panel, dict):
                panel = {}
                payload["panel"] = panel
            panel["customDevices"] = disk_panel["customDevices"]
        atomic_write_settings(path, payload)
        return payload
