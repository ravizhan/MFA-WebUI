"""Update-gate transitions owned by perform_update (no coordinator setter)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(main_module):
    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    main_module.app.router.lifespan_context = noop_lifespan
    with TestClient(main_module.app, raise_server_exceptions=False) as c:
        yield c, main_module


def test_download_failure_clears_update_gate(client, monkeypatch, tmp_path):
    c, main = client
    main.app_state.update_info = {
        "file_name": str(tmp_path / "pkg.zip"),
        "download_url": "http://example.test/pkg.zip",
        "download_source": "github",
        "file_hash": "",
    }
    main.app_state.execution_coordinator = SimpleNamespace(active_run=lambda: None)
    main.app_state.update_in_progress = False

    async def boom(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(main, "download_file", boom)

    resp = c.get("/api/update")
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"
    assert main.app_state.update_in_progress is False


def test_hash_failure_clears_update_gate(client, monkeypatch, tmp_path):
    c, main = client
    pkg = tmp_path / "pkg.zip"
    main.app_state.update_info = {
        "file_name": str(pkg),
        "download_url": "http://example.test/pkg.zip",
        "download_source": "github",
        "file_hash": "deadbeef",
    }
    main.app_state.execution_coordinator = SimpleNamespace(active_run=lambda: None)

    async def fake_download(url, path, proxy=None):
        with open(path, "wb") as f:
            f.write(b"not-matching")

    monkeypatch.setattr(main, "download_file", fake_download)

    resp = c.get("/api/update")
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"
    assert main.app_state.update_in_progress is False


def test_popen_failure_clears_update_gate(client, monkeypatch, tmp_path):
    c, main = client
    pkg = tmp_path / "pkg.zip"
    pkg.write_bytes(b"x")
    main.app_state.update_info = {
        "file_name": str(pkg),
        "download_url": "http://example.test/pkg.zip",
        "download_source": "github",
        "file_hash": "",
    }
    main.app_state.execution_coordinator = SimpleNamespace(active_run=lambda: None)

    async def fake_download(*_args, **_kwargs):
        return None

    monkeypatch.setattr(main, "download_file", fake_download)

    def boom_popen(*_args, **_kwargs):
        raise OSError("no updater binary")

    # 同步跑线程体：用 threading.Thread 替换为立即执行
    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    monkeypatch.setattr(main.subprocess, "Popen", boom_popen)
    monkeypatch.setattr(main.threading, "Thread", ImmediateThread)

    resp = c.get("/api/update")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert main.app_state.update_in_progress is False
    assert main.app_state.update_status["status"] == "failed"


def test_nonzero_exit_clears_update_gate(client, monkeypatch, tmp_path):
    c, main = client
    pkg = tmp_path / "pkg.zip"
    pkg.write_bytes(b"x")
    main.app_state.update_info = {
        "file_name": str(pkg),
        "download_url": "http://example.test/pkg.zip",
        "download_source": "github",
        "file_hash": "",
    }
    main.app_state.execution_coordinator = SimpleNamespace(active_run=lambda: None)

    async def fake_download(*_args, **_kwargs):
        return None

    monkeypatch.setattr(main, "download_file", fake_download)

    proc = MagicMock()
    proc.stdout = iter([])
    proc.wait = MagicMock(return_value=None)
    proc.returncode = 2

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    monkeypatch.setattr(main.subprocess, "Popen", MagicMock(return_value=proc))
    monkeypatch.setattr(main.threading, "Thread", ImmediateThread)

    resp = c.get("/api/update")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert main.app_state.update_in_progress is False


def test_code_10_keeps_gate_then_code_0_keeps_gate(client, monkeypatch, tmp_path):
    """code 10 自更新保持闸门；随后 code 0 成功交接仍保持。"""
    c, main = client
    pkg = tmp_path / "pkg.zip"
    pkg.write_bytes(b"x")
    main.app_state.update_info = {
        "file_name": str(pkg),
        "download_url": "http://example.test/pkg.zip",
        "download_source": "github",
        "file_hash": "",
    }
    main.app_state.execution_coordinator = SimpleNamespace(active_run=lambda: None)

    async def fake_download(*_args, **_kwargs):
        return None

    monkeypatch.setattr(main, "download_file", fake_download)

    codes = iter([10, 0])

    def make_proc(*_args, **_kwargs):
        proc = MagicMock()
        proc.stdout = iter([])
        proc.wait = MagicMock(return_value=None)
        proc.returncode = next(codes)
        return proc

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    monkeypatch.setattr(main.subprocess, "Popen", make_proc)
    monkeypatch.setattr(main.threading, "Thread", ImmediateThread)

    resp = c.get("/api/update")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert main.app_state.update_in_progress is True
