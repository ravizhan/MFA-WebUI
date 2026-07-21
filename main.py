import argparse
import asyncio
import hashlib
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import json_utils as json
from app_state import AppState, LogBroadcaster, normalize_event
from maa_utils import MaaWorker
from models.api import CustomDeviceCreate, DeviceModel
from models.interface_loader import (
    InterfaceLoadError,
    load_interface_model,
    rescan_scan_select_option,
    resolve_interface_relative_path,
)
from models.scheduler import (
    ManualStartPayload,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
)
from models.settings import SettingsModel
from models.task_config import (
    TaskConfigModel,
    normalize_task_config,
)
from scheduler_manager import SchedulerManager
from services.execution_coordinator import ExecutionCoordinator
from services.execution_store import ExecutionStore
from services.process_lock import LockBusyError, LockError, RuntimeOwnership
from services.system_scheduler import SystemScheduler
from services.update_service import (
    check_github_update,
    check_mirrorchyan_update,
    download_file,
    get_platform_info,
)
import settings_io


def _resolve_app_root_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_ROOT_DIR = _resolve_app_root_dir()
CONFIG_DIR = APP_ROOT_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
TASK_CONFIG_FILE = CONFIG_DIR / "task_config.json"
LOGS_DIR = CONFIG_DIR / "logs"
INDEX_FILE = APP_ROOT_DIR / "page/index.html"
NATIVE_TOKEN_FILE = CONFIG_DIR / "native_token"
SCHEDULER_DB_PATH = CONFIG_DIR / "scheduler.sqlite"

EXIT_SUCCESS = 0
EXIT_APP_RUNNING = 4
EXIT_UPDATING = 5
EXIT_DELEGATE_FAILED = 1


def load_interface_translations() -> dict[str, dict]:
    translations: dict[str, dict] = {}
    for locale, relative_path in (interface.languages or {}).items():
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise InterfaceLoadError(f"languages[{locale}] 必须是非空字符串")

        resolved_path = resolve_interface_relative_path(
            APP_ROOT_DIR,
            relative_path,
            field_name=f"languages[{locale}]",
        )
        try:
            with resolved_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            message = getattr(exc, "message", str(exc))
            raise InterfaceLoadError(
                f"解析语言文件失败: {resolved_path}: {message}"
            ) from exc

        if not isinstance(data, dict):
            raise InterfaceLoadError(f"语言文件必须是 JSON 对象: {resolved_path}")
        translations[locale] = data
    return translations


try:
    interface = load_interface_model(APP_ROOT_DIR)
    interface_translations = load_interface_translations()
except Exception as e:
    print(e)
    input("interface.json加载异常，请修正后重新启动程序，按任意键退出...")
    exit(1)

interface_lock = threading.Lock()


class ScanSelectRescanRequest(BaseModel):
    option_name: str


if not CONFIG_DIR.exists():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with SETTINGS_FILE.open("w", encoding="utf-8") as f:
        json.dump(SettingsModel().model_dump(), f, indent=4, ensure_ascii=False)
    with TASK_CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(TaskConfigModel().model_dump(), f, indent=4, ensure_ascii=False)


app_state = AppState(APP_ROOT_DIR)


async def log_monitor():
    while not app_state.is_shutting_down:
        while not app_state.message_conn.empty():
            message = normalize_event(app_state.message_conn.get_nowait())
            app_state.history_message.append(message)
            if app_state.broadcaster:
                await app_state.broadcaster.broadcast(message)
        await asyncio.sleep(0.1)


def acquire_runtime_ownership() -> RuntimeOwnership:
    """获取进程级运行时锁；仅在真实 CLI 启动时调用，不在 import/测试路径。"""
    ownership = RuntimeOwnership(APP_ROOT_DIR)
    ownership.acquire()
    return ownership


def release_runtime_ownership() -> None:
    """释放运行时锁；失败时静默，避免关闭路径二次异常。"""
    ownership = app_state.runtime_ownership
    if ownership is not None:
        try:
            ownership.release()
        except Exception:
            pass
        app_state.runtime_ownership = None


def ensure_native_token() -> str:
    """读取或创建 config/native_token（权限 0600），供 native 二次进程鉴权。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not NATIVE_TOKEN_FILE.exists():
        token = secrets.token_hex(32)
        NATIVE_TOKEN_FILE.write_text(token, encoding="utf-8")
        try:
            os.chmod(NATIVE_TOKEN_FILE, 0o600)
        except OSError:
            pass
        return token
    return NATIVE_TOKEN_FILE.read_text(encoding="utf-8").strip()


def delegate_native_dispatch(task_id: str) -> int:
    """
    本实例抢锁失败时，将 native 唤醒委托给已运行实例。
    仅 2xx 视为成功；4xx/5xx/重试耗尽均返回 EXIT_DELEGATE_FAILED。
    """
    if not NATIVE_TOKEN_FILE.exists():
        print("native_token 不存在，无法委托", file=sys.stderr)
        return EXIT_DELEGATE_FAILED
    token = NATIVE_TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        print("native_token 为空，无法委托", file=sys.stderr)
        return EXIT_DELEGATE_FAILED

    url = "http://127.0.0.1:5566/api/internal/scheduler/native-dispatch"
    payload = {"task_id": task_id, "token": token}
    deadline = time.monotonic() + 30.0
    last_err = "unknown"
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(url, json=payload)
            # 2xx 成功；4xx 不重试；5xx 继续重试
            if 200 <= resp.status_code < 300:
                return EXIT_SUCCESS
            if 400 <= resp.status_code < 500:
                print(
                    f"native-dispatch 响应 {resp.status_code}: {resp.text}",
                    file=sys.stderr,
                )
                return EXIT_DELEGATE_FAILED
            last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(2.0)
    print(f"native-dispatch 委托失败（已重试）: {last_err}", file=sys.stderr)
    return EXIT_DELEGATE_FAILED


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：初始化调度/准入，退出时释放运行时锁。"""
    app_state.is_shutting_down = False
    app_state.worker = MaaWorker(app_state, interface)
    app_state.broadcaster = LogBroadcaster()
    app_state.native_token = ensure_native_token()

    with SETTINGS_FILE.open("r", encoding="utf-8") as f:
        config_data = json.load(f)
    with interface_lock:
        app_state.settings = SettingsModel.model_validate(
            config_data,
            context={"interface": interface},
        )

    # 执行存储 + 准入协调器（唯一任务入口）
    app_state.execution_store = ExecutionStore(SCHEDULER_DB_PATH)
    await asyncio.to_thread(app_state.execution_store.init)
    app_state.execution_coordinator = ExecutionCoordinator(
        app_state, app_state.execution_store
    )

    # 系统级唤醒适配器（无状态）
    app_state.system_scheduler = SystemScheduler(APP_ROOT_DIR)

    # APS 先暂停，等 OS 注册 converge 完成后再 resume，避免竞态
    # 构造契约：SchedulerManager(state, db_path, system_scheduler=None)
    app_state.scheduler_manager = SchedulerManager(
        app_state,
        SCHEDULER_DB_PATH,
        system_scheduler=app_state.system_scheduler,
    )
    await app_state.scheduler_manager.initialize(paused=True)

    # 将 OS 注册收敛到 APS 期望集合（enabled + wakeup_enabled）
    try:
        all_tasks = await app_state.scheduler_manager.get_all_tasks()
        desired = [t for t in all_tasks if t.wakeup_enabled and t.enabled]
        report = app_state.system_scheduler.converge(desired)
        if report.failed:
            app_state.send_log(f"系统任务 converge 有失败: {report.failed}")
        if report.registered or report.unregistered:
            app_state.send_log(
                f"系统任务 converge: 注册 {len(report.registered)}, "
                f"注销 {len(report.unregistered)}"
            )
    except Exception as e:
        app_state.send_log(f"系统任务 converge 失败: {e}")

    app_state.scheduler_manager.resume()
    app_state.send_log("调度器已恢复派发")

    # 冷启动 native 唤醒：resume 后作为后台任务执行
    pending_id = app_state.pending_scheduled_task_id
    if pending_id and app_state.execution_coordinator is not None:

        async def _run_pending_native():
            assert app_state.scheduler_manager is not None
            assert app_state.execution_coordinator is not None
            try:
                task = await app_state.scheduler_manager.get_task(pending_id)
                if task is None:
                    app_state.send_log(
                        f"启动参数 --scheduled-task 任务不存在: {pending_id}"
                    )
                    return
                # 冷启动 native 仅接受 enabled + wakeup_enabled
                if not task.enabled or not task.wakeup_enabled:
                    app_state.send_log(
                        f"启动参数 --scheduled-task 任务未启用原生唤醒: {pending_id}"
                    )
                    return
                await app_state.execution_coordinator.submit_scheduled(
                    task, origin="native"
                )
            except Exception as e:
                app_state.send_log(f"启动 native 任务失败: {e}")

        asyncio.create_task(_run_pending_native())

    monitor_task = asyncio.create_task(log_monitor())
    webbrowser.open_new("http://127.0.0.1:5566")
    yield
    await teardown_runtime(monitor_task)


async def teardown_runtime(monitor_task: asyncio.Task) -> None:
    """
    正常关闭顺序：停调度器 → 等待活跃执行落库清理 → worker → log_monitor。
    运行时锁在 finally 中释放，避免中途异常泄漏。
    """
    app_state.is_shutting_down = True
    try:
        # 1. 先停 APS，阻止新的 scheduled 回调入场
        if app_state.scheduler_manager is not None:
            await app_state.scheduler_manager.shutdown()

        # 2. 有活跃执行则请求停止并等待后台完成协程（含 store.finish / 清槽）
        coordinator = app_state.execution_coordinator
        if coordinator is not None and coordinator.active_run() is not None:
            await coordinator.stop_active()

        # 3. 执行结束后再关 worker
        if app_state.worker is not None:
            app_state.worker.shutdown()

        # 4. 最后停日志监视
        monitor_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task
    finally:
        release_runtime_ownership()


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=str(APP_ROOT_DIR / "page/assets")))
app.mount("/resource", StaticFiles(directory=str(APP_ROOT_DIR / "resource")))


def _load_normalized_task_config() -> tuple[TaskConfigModel, bool]:
    config_exists = TASK_CONFIG_FILE.exists()

    if config_exists:
        with TASK_CONFIG_FILE.open("r", encoding="utf-8") as f:
            config_data = json.load(f)
    else:
        config_data = TaskConfigModel().model_dump()

    task_config = TaskConfigModel(**config_data)
    normalized_config = normalize_task_config(task_config, interface)
    normalized_data = normalized_config.model_dump()

    should_write_back = (not config_exists) or config_data != normalized_data
    if should_write_back:
        with TASK_CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(normalized_data, f, indent=4, ensure_ascii=False)

    return normalized_config, should_write_back


@app.middleware("http")
async def spa_middleware(request: Request, call_next):
    response = await call_next(request)
    if response.status_code == 404 and not (
        request.url.path.startswith("/api/")
        or request.url.path.startswith("/assets/")
        or request.url.path.startswith("/resource/")
    ):
        return FileResponse(INDEX_FILE)
    return response


@app.get("/")
async def serve_homepage():
    return FileResponse(INDEX_FILE)


@app.get("/api/file")
def get_file(path: str):
    try:
        resolved_path = resolve_interface_relative_path(
            APP_ROOT_DIR,
            path,
            field_name="path",
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if ("不存在" in message or "不是文件" in message) else 400
        return JSONResponse(
            status_code=status_code,
            content={"status": "failed", "message": message},
        )
    return FileResponse(resolved_path)


@app.get("/api/interface")
def get_interface():
    with interface_lock:
        data = interface.model_dump(mode="json")
        if interface_translations:
            data["translations"] = interface_translations
        return data


@app.post("/api/interface/scan-select/rescan")
def rescan_scan_select(payload: ScanSelectRescanRequest):
    option_name = payload.option_name.strip()
    if not option_name:
        return {"status": "failed", "message": "option_name 不能为空"}

    try:
        with interface_lock:
            cases = rescan_scan_select_option(interface, option_name, APP_ROOT_DIR)
    except InterfaceLoadError as exc:
        return {"status": "failed", "message": str(exc)}
    except Exception as exc:
        app_state.send_log(f"重扫 scan_select 失败: {exc}")
        return {"status": "failed", "message": "重扫失败"}

    return {
        "status": "success",
        "option_name": option_name,
        "cases": cases,
    }


async def video_stream_generator(fps: int = 15):
    fps = max(1, min(60, fps))
    interval = 1.0 / fps

    while not app_state.is_shutting_down:
        if app_state.worker and app_state.device.connected:
            frame_bytes = await asyncio.to_thread(app_state.worker.get_screencap_bytes)
            if frame_bytes:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                )
                await asyncio.sleep(interval)
                continue
        await asyncio.sleep(0.5)


@app.get("/api/stream/live")
async def stream_live(fps: int = 15):
    return StreamingResponse(
        video_stream_generator(fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/device")
def get_device(controller: str | None = None):
    if app_state.worker is None:
        return {"status": "failed", "message": "Worker未初始化"}
    data = app_state.worker.device.get_device(controller)
    return {"status": "success", "data": data}


@app.post("/api/device")
async def connect_device(device: DeviceModel):
    if app_state.worker is None:
        msg = "Worker未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    if await asyncio.to_thread(app_state.worker.device.connect, device):
        return {"status": "success"}
    msg = app_state.device.last_device_error or "设备连接失败"
    return {"status": "failed", "message": msg}


@app.post("/api/device/custom")
def add_custom_device(payload: CustomDeviceCreate):
    if app_state.worker is None:
        return {"status": "failed", "message": "Worker未初始化"}
    try:
        device = app_state.worker.device.add_custom_device(payload)
        return {"status": "success", "data": device}
    except ValueError as e:
        return {"status": "failed", "message": str(e)}
    except OSError as e:
        return {"status": "failed", "message": f"保存自定义设备失败: {e}"}


@app.get("/api/device/state")
def get_device_state():
    if app_state.worker is None:
        return {"status": "failed", "message": "Worker未初始化"}
    if app_state.device.connected and not app_state.worker.device.is_connection_alive():
        app_state.worker.device.reset_connection_state(
            "检测到设备连接已断开，已解除设备与资源锁定"
        )

    return {
        "status": "success",
        "state": {
            "connected": app_state.device.connected,
            "configuration_locked": app_state.device.configuration_locked,
            "controller_name": app_state.device.controller_name,
            "resource_name": app_state.device.current_resource_name,
        },
    }


@app.get("/api/resource")
def get_resource(controller_type: str | None = Query(default=None)):
    if app_state.worker is None:
        return {"status": "failed", "message": "Worker未初始化"}
    resources = [
        {
            "name": r.name,
            "label": r.label,
            "controller": r.controller,
        }
        for r in interface.resource
    ]
    if controller_type:
        try:
            from maa_worker.resource_utils import filter_resources_by_controller_type

            resources = filter_resources_by_controller_type(resources, controller_type)
        except ImportError:
            pass
    return {"status": "success", "resource": resources}


@app.post("/api/resource")
async def set_resource(name: str):
    """为已连接设备加载指定资源。"""
    if app_state.worker is None:
        msg = "Worker未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    if not app_state.device.connected:
        msg = "请先连接设备后再选择资源"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        ok = await asyncio.to_thread(app_state.worker.device.set_resource, name)
        if not ok:
            msg = app_state.device.last_resource_error or "设置资源失败"
            return {"status": "failed", "message": msg}
    except Exception as e:
        app_state.send_log(f"设置资源失败: {e}")
        return {"status": "failed", "message": str(e)}
    return {"status": "success"}


@app.get("/api/settings")
def get_settings():
    with interface_lock:
        app_state.settings = settings_io.load_settings_model(
            SETTINGS_FILE,
            context={"interface": interface},
        )
    return {"status": "success", "settings": app_state.settings.model_dump()}


@app.post("/api/settings")
def set_settings(settings: SettingsModel):
    written = settings_io.write_settings_preserving_custom_devices(
        SETTINGS_FILE, settings
    )
    # Re-validate so app_state reflects preserved customDevices from disk.
    with interface_lock:
        app_state.settings = SettingsModel.model_validate(
            written,
            context={"interface": interface},
        )
    return {"status": "success"}


@app.get("/api/task-config")
def get_task_config():
    try:
        task_config, _ = _load_normalized_task_config()
        return {"status": "success", "config": task_config.model_dump()}
    except Exception as e:
        app_state.send_log(f"获取任务配置失败: {e}")
        return {"status": "failed", "message": str(e)}


@app.post("/api/task-config")
def save_task_config(config: TaskConfigModel):
    try:
        normalized_config = normalize_task_config(config, interface)
        with TASK_CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(normalized_config.model_dump(), f, indent=4, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        app_state.send_log(f"保存任务配置失败: {e}")
        return {"status": "failed", "message": str(e)}


@app.delete("/api/task-config")
def reset_task_config():
    try:
        if TASK_CONFIG_FILE.exists():
            TASK_CONFIG_FILE.unlink()
        return {"status": "success"}
    except Exception as e:
        app_state.send_log(f"重置任务配置失败: {e}")
        return {"status": "failed", "message": str(e)}


@app.get("/api/update/check")
def check_update():
    try:
        settings = app_state.settings or SettingsModel()
        current_version = interface.version or ""
        mirrorchyan_rid = getattr(interface, "mirrorchyan_rid", None)
        github_url = interface.github or ""
        cdk = settings.update.mirrorchyanCdk

        if mirrorchyan_rid:
            mc_data = check_mirrorchyan_update(
                mirrorchyan_rid, current_version, cdk, settings
            )
            if mc_data and mc_data.get("code") == 0:
                mc_info = mc_data.get("data", {})
                latest_version = mc_info.get("version_name", "")
                has_update = latest_version and latest_version != current_version

                app_state.update_info = {
                    "latest_version": latest_version,
                    "current_version": current_version,
                    "is_update_available": has_update,
                    "release_notes": mc_info.get("release_note", ""),
                    "download_url": mc_info.get("url", ""),
                    "file_hash": mc_info.get("sha256", ""),
                    "file_name": f"update-{latest_version}.7z",
                    "download_source": "mirrorchyan",
                    "update_type": mc_info.get("update_type", "full"),
                }

                # 有 CDK 且有下载链接，直接返回 mirrorchyan 结果
                if app_state.update_info["download_url"]:
                    return {
                        "status": "success",
                        "update_info": app_state.update_info,
                    }

                # 无 CDK 或无下载链接，尝试 GitHub 获取下载链接
                if has_update and github_url:
                    try:
                        gh_info = check_github_update(
                            github_url,
                            current_version,
                            settings,
                        )
                        if gh_info:
                            # 保留 mirrorchyan 的版本信息，用 GitHub 的下载链接
                            app_state.update_info["download_url"] = gh_info[
                                "download_url"
                            ]
                            app_state.update_info["file_hash"] = gh_info["file_hash"]
                            app_state.update_info["file_name"] = gh_info["file_name"]
                            app_state.update_info["download_source"] = "github"
                    except Exception:
                        pass

                return {
                    "status": "success",
                    "update_info": app_state.update_info,
                }

        if github_url:
            gh_info = check_github_update(github_url, current_version, settings)
            if gh_info:
                app_state.update_info = gh_info
                return {"status": "success", "update_info": app_state.update_info}

            plat, arch = get_platform_info()
            msg = f"未找到适合当前平台的更新包:{plat}-{arch}"
            app_state.send_log(msg)
            return {
                "status": "failed",
                "message": msg,
            }

        msg = "未配置更新源"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"检查更新失败: {msg}")
        return {"status": "failed", "message": msg}


@app.get("/api/update")
async def perform_update():
    """下载并后台执行更新；有活跃任务时拒绝，并置 update 闸门。"""
    try:
        coordinator = app_state.execution_coordinator
        # 与任务准入互斥，避免更新过程中再开任务
        if coordinator is not None and coordinator.active_run() is not None:
            msg = "任务执行中，无法更新"
            app_state.send_log(msg)
            return {"status": "failed", "message": msg}

        if app_state.update_info is None:
            msg = "暂无可用更新信息"
            app_state.send_log(msg)
            return {"status": "failed", "message": msg}

        # 直接持有更新闸门；普通失败释放，code 10 / 成功 0 保持
        app_state.update_in_progress = True

        update_package_path = app_state.update_info["file_name"]
        download_url = app_state.update_info["download_url"]
        download_source = app_state.update_info.get("download_source", "github")
        if os.path.exists(update_package_path):
            os.remove(update_package_path)
        app_state.update_status = {
            "status": "downloading",
            "message": "正在下载更新包...",
        }

        try:
            raw_proxy = (
                (app_state.settings or SettingsModel()).update.proxy
                if download_source != "mirrorchyan"
                else None
            )
            proxy = (
                raw_proxy.strip()
                if isinstance(raw_proxy, str) and raw_proxy.strip()
                else None
            )
            await download_file(download_url, update_package_path, proxy)
            file_hash = app_state.update_info.get("file_hash", "")
            if file_hash:
                with open(update_package_path, "rb") as f:
                    file_bytes = f.read()
                    sha256_hash = hashlib.sha256(file_bytes).hexdigest()
                    if sha256_hash != file_hash:
                        raise ValueError("文件哈希校验失败，下载的文件可能已损坏。")
        except Exception as e:
            app_state.update_in_progress = False
            msg = f"下载失败: {e}"
            app_state.send_log(msg)
            app_state.update_status = {"status": "failed", "message": msg}
            return {"status": "failed", "message": str(e)}

        def run_updater_loop():
            app_state.update_status = {
                "status": "updating",
                "message": "正在运行更新器...",
            }
            while True:
                cmd = [
                    "./mwu-updater",
                    "-archive",
                    os.path.abspath(update_package_path),
                    "-webhook",
                    "http://127.0.0.1:5566/api/system/shutdown",
                    "-restart-cmd",
                    sys.executable,
                ]

                try:
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )

                    if process.stdout:
                        for line in process.stdout:
                            print(f"[Updater] {line.strip()}")
                            try:
                                data = json.loads(line)
                                if "status" in data:
                                    app_state.update_status = data
                            except json.JSONDecodeError:
                                pass
                except Exception as e:
                    app_state.update_in_progress = False
                    msg = f"启动更新器失败: {e}"
                    app_state.send_log(msg)
                    app_state.update_status = {
                        "status": "failed",
                        "message": msg,
                    }
                    break

                process.wait()

                if process.returncode == 10:
                    # 自更新交接：保持闸门
                    app_state.update_status = {
                        "status": "updating",
                        "message": "更新器自更新完成，正在重启更新器...",
                    }
                    continue
                if process.returncode != 0:
                    app_state.update_in_progress = False
                    msg = f"更新器异常退出: {process.returncode}，请查看updater.log"
                    app_state.send_log(msg)
                    app_state.update_status = {
                        "status": "failed",
                        "message": msg,
                    }
                # returncode == 0：成功交接，保持 update_in_progress
                break

        threading.Thread(target=run_updater_loop, daemon=True).start()
        return {"status": "success", "message": "正在后台更新程序..."}
    except Exception as e:
        app_state.update_in_progress = False
        msg = str(e)
        app_state.send_log(f"更新失败: {msg}")
        app_state.update_status = {"status": "failed", "message": msg}
        return {"status": "failed", "message": msg}


@app.get("/api/update/status")
def get_update_status():
    if app_state.update_status is None:
        return {"status": "idle", "message": "没有正在进行的更新"}
    return app_state.update_status


@app.get("/api/system/shutdown")
def system_shutdown():
    def _shutdown():
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_shutdown, daemon=True).start()
    return {"status": "success", "message": "Shutting down"}


@app.post("/api/test-notification")
def test_notification():
    if app_state.worker is None:
        msg = "Worker未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        app_state.worker.events.send_notification(
            "测试通知",
            "这是一条测试通知。",
            event="notification.test",
        )
        return {"status": "success"}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"发送测试通知失败: {msg}")
        return {"status": "failed", "message": msg}


@app.post("/api/start")
async def start(payload: ManualStartPayload):
    """手动启动：经 ExecutionCoordinator 准入，冲突时返回 conflict。"""
    if app_state.execution_coordinator is None:
        msg = "执行协调器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        admission = await app_state.execution_coordinator.submit_manual(payload)
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"启动任务失败: {msg}")
        return {"status": "failed", "message": msg}

    if admission.accepted:
        return {"status": "success", "run_id": admission.run_id}
    if admission.conflict is not None:
        return {
            "status": "conflict",
            "conflict": admission.conflict.model_dump(mode="json"),
        }
    return {"status": "failed", "message": "任务启动被拒绝"}


@app.post("/api/stop")
async def stop():
    """停止当前活跃运行（经协调器，非直接操作 worker）。"""
    if app_state.execution_coordinator is None:
        msg = "执行协调器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    stopped = await app_state.execution_coordinator.stop_active()
    if not stopped:
        msg = "任务未开始"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    return {"status": "success"}


@app.get("/api/logs")
async def stream_logs(request: Request):
    if app_state.broadcaster is None:

        async def empty_generator():
            while (
                not app_state.is_shutting_down and not await request.is_disconnected()
            ):
                yield ": keep-alive\n\n"
                await asyncio.sleep(15)

        return StreamingResponse(empty_generator(), media_type="text/event-stream")

    q = app_state.broadcaster.add_client(app_state.history_message)

    async def event_generator():
        try:
            while not app_state.is_shutting_down:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {json.dumps(data.model_dump(), ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            if app_state.broadcaster is not None:
                app_state.broadcaster.remove_client(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/scheduler/tasks")
async def get_scheduler_tasks():
    """获取所有定时任务"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        tasks = await app_state.scheduler_manager.get_all_tasks()
        return {"status": "success", "tasks": [task.model_dump() for task in tasks]}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"获取调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.post("/api/scheduler/tasks")
async def create_scheduler_task(task_create: ScheduledTaskCreate):
    """创建定时任务；OS native 注册由 SchedulerManager 内联处理。"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        task = await app_state.scheduler_manager.create_task(task_create)
        return {"status": "success", "task": task.model_dump(mode="json")}
    except (ValueError, RuntimeError) as e:
        msg = str(e)
        app_state.send_log(f"创建调度任务失败: {msg}")
        return JSONResponse(
            status_code=400,
            content={"status": "failed", "message": msg},
        )
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"创建调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.put("/api/scheduler/tasks/{task_id}")
async def update_scheduler_task(task_id: str, task_update: ScheduledTaskUpdate):
    """更新定时任务；native 注册/注销在 manager 内联。"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        task = await app_state.scheduler_manager.update_task(task_id, task_update)
        if task is None:
            msg = "任务不存在"
            app_state.send_log(msg)
            return {"status": "failed", "message": msg}
        return {"status": "success", "task": task.model_dump(mode="json")}
    except (ValueError, RuntimeError) as e:
        msg = str(e)
        app_state.send_log(f"更新调度任务失败: {msg}")
        return JSONResponse(
            status_code=400,
            content={"status": "failed", "message": msg},
        )
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"更新调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.delete("/api/scheduler/tasks/{task_id}")
async def delete_scheduler_task(task_id: str):
    """删除定时任务"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        success = await app_state.scheduler_manager.delete_task(task_id)
        if success:
            return {"status": "success"}
        msg = "任务不存在"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"删除调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.post("/api/scheduler/tasks/{task_id}/pause")
async def pause_scheduler_task(task_id: str):
    """暂停定时任务"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        success = await app_state.scheduler_manager.pause_task(task_id)
        if success:
            return {"status": "success"}
        msg = "任务不存在"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"暂停调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.post("/api/scheduler/tasks/{task_id}/resume")
async def resume_scheduler_task(task_id: str):
    """恢复定时任务"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        success = await app_state.scheduler_manager.resume_task(task_id)
        if success:
            return {"status": "success"}
        msg = "任务不存在"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"恢复调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.get("/api/scheduler/executions")
async def get_scheduler_executions(limit: int = 50):
    """获取执行历史（读 ExecutionStore，不再经 SchedulerManager）。"""
    if app_state.execution_store is None:
        msg = "执行存储未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        executions = await asyncio.to_thread(app_state.execution_store.list, limit)
        return {
            "status": "success",
            "executions": [ex.model_dump(mode="json") for ex in executions],
        }
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"获取调度执行历史失败: {msg}")
        return {"status": "failed", "message": msg}


class NativeDispatchRequest(BaseModel):
    """native 二次进程移交请求：任务 id + 本机 token。"""

    task_id: str
    token: str


@app.post("/api/internal/scheduler/native-dispatch")
async def native_dispatch(body: NativeDispatchRequest):
    """OS native 二次进程把任务移交给已运行的 MWU 实例。"""
    if not app_state.native_token or body.token != app_state.native_token:
        app_state.send_log(
            f"native-dispatch 鉴权失败 task_id={body.task_id}（token 不匹配或为空）"
        )
        return JSONResponse(
            status_code=401,
            content={"status": "failed", "message": "invalid token"},
        )
    if app_state.scheduler_manager is None or app_state.execution_coordinator is None:
        app_state.send_log(f"native-dispatch 拒绝 task_id={body.task_id}：调度器未就绪")
        return JSONResponse(
            status_code=503,
            content={"status": "failed", "message": "scheduler not ready"},
        )
    task = await app_state.scheduler_manager.get_task(body.task_id)
    if task is None:
        app_state.send_log(
            f"native-dispatch 收到不存在的任务 id={body.task_id}（可能已被删除）"
        )
        return JSONResponse(
            status_code=404,
            content={"status": "failed", "message": "task not found"},
        )
    # HTTP native 仅接受 enabled + wakeup_enabled；否则扁平 409
    if not task.enabled or not task.wakeup_enabled:
        app_state.send_log(
            f"native-dispatch 拒绝 task_id={body.task_id}："
            f"enabled={task.enabled} wakeup_enabled={task.wakeup_enabled}"
        )
        return JSONResponse(
            status_code=409,
            content={
                "status": "failed",
                "message": "task not enabled for native wakeup",
            },
        )
    admission = await app_state.execution_coordinator.submit_scheduled(
        task, origin="native"
    )
    if admission.accepted:
        app_state.send_log(
            f"native-dispatch 入场 task={task.name} run_id={admission.run_id}"
        )
    else:
        app_state.send_log(
            f"native-dispatch 跳过 task={task.name} 原因={admission.skip_status}"
        )
    return {
        "status": "success",
        "accepted": admission.accepted,
        "run_id": admission.run_id,
        "skip_status": admission.skip_status,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MWU - MaaFramework WebUI")
    parser.add_argument(
        "--scheduled-task",
        type=str,
        default=None,
        help="启动后执行指定定时任务（native 唤醒 / 冷启动）",
    )
    args = parser.parse_args()
    app_state.pending_scheduled_task_id = args.scheduled_task

    try:
        app_state.runtime_ownership = acquire_runtime_ownership()
    except LockBusyError as e:
        msg = str(e).lower()
        if "update" in msg:
            print("更新进行中，无法启动")
            sys.exit(EXIT_UPDATING)
        if args.scheduled_task:
            sys.exit(delegate_native_dispatch(args.scheduled_task))
        print("应用已在运行")
        sys.exit(EXIT_APP_RUNNING)
    except LockError as e:
        print(f"锁协议失败: {e}")
        sys.exit(EXIT_UPDATING)

    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=5566,
            timeout_graceful_shutdown=1,
        )
    finally:
        release_runtime_ownership()
