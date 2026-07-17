import argparse
import asyncio
import hashlib
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path

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
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
    TaskExecutionPayload,
)
from models.settings import SettingsModel
from models.task_config import (
    TaskConfigModel,
    normalize_task_config,
    normalize_task_execution_payload,
)
from scheduler_manager import SchedulerManager
from services.process_lock import LockBusyError, LockError, RuntimeOwnership
from services.system_scheduler import SystemTaskService
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

# Headless 模式退出码
EXIT_SUCCESS = 0
EXIT_TASK_NOT_FOUND = 1
EXIT_DEVICE_FAILED = 2
EXIT_TASK_FAILED = 3
EXIT_APP_RUNNING = 4
EXIT_UPDATING = 5


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


app_state = AppState()


async def log_monitor():
    while not app_state.is_shutting_down:
        while not app_state.message_conn.empty():
            message = normalize_event(app_state.message_conn.get_nowait())
            app_state.history_message.append(message)
            if app_state.broadcaster:
                await app_state.broadcaster.broadcast(message)
        await asyncio.sleep(0.1)


def acquire_runtime_ownership() -> RuntimeOwnership:
    """Acquire process-lifetime runtime lock (not on import/test)."""
    ownership = RuntimeOwnership(APP_ROOT_DIR)
    ownership.acquire()
    return ownership


def release_runtime_ownership() -> None:
    ownership = app_state.runtime_ownership
    if ownership is not None:
        try:
            ownership.release()
        except Exception:
            pass
        app_state.runtime_ownership = None


async def _headless_log_consumer(logger: logging.Logger):
    """Headless 模式日志消费者：从队列读取事件并写入日志文件"""
    while True:
        while not app_state.message_conn.empty():
            message = normalize_event(app_state.message_conn.get_nowait())
            level = logging.INFO
            if hasattr(message, "level"):
                level_map = {
                    "error": logging.ERROR,
                    "warning": logging.WARNING,
                    "info": logging.INFO,
                }
                level = level_map.get(message.level, logging.INFO)
            logger.log(level, f"[{message.event}] {message.message}")
        await asyncio.sleep(0.1)


async def run_headless(task_id: str) -> int:
    """Headless 模式：不启动 Web 服务器，执行指定任务后退出

    流程：
    1. Runtime ownership（update 锁 30s + runtime 独占 + recheck）
    2. 文件日志（失败也释放锁）
    3. MaaWorker + SchedulerManager（paused，无后台派发）
    4. 拒绝禁用任务；执行恰好一个 job
    5. 清理并退出
    """
    ownership = None
    file_handler = None
    root_logger = logging.getLogger()
    scheduler_manager = None
    worker = None
    log_task = None

    try:
        try:
            ownership = acquire_runtime_ownership()
            app_state.runtime_ownership = ownership
        except LockBusyError as e:
            msg = str(e).lower()
            if "update" in msg:
                print("更新进行中，跳过执行")
                return EXIT_UPDATING
            print("应用已在运行，委托现有实例处理")
            return EXIT_APP_RUNNING
        except LockError as e:
            print(f"锁协议失败: {e}")
            return EXIT_UPDATING

        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = LOGS_DIR / f"headless_{task_id}_{timestamp}.log"
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            )
            root_logger.addHandler(file_handler)
            root_logger.setLevel(logging.INFO)
        except Exception as e:
            print(f"日志初始化失败: {e}")
            return EXIT_TASK_FAILED

        logger = logging.getLogger("headless")
        logger.info(f"Headless 模式启动，任务 ID: {task_id}")

        worker = MaaWorker(app_state.message_conn, interface, APP_ROOT_DIR)
        scheduler_manager = SchedulerManager()
        scheduler_manager.set_worker(worker)
        await scheduler_manager.initialize(start_scheduler=True, paused=True)

        log_task = asyncio.create_task(_headless_log_consumer(logger))

        if scheduler_manager.scheduler is None:
            logger.error("调度器未初始化")
            return EXIT_TASK_FAILED
        job = scheduler_manager.scheduler.get_job(task_id)
        if job is None:
            logger.error(f"APScheduler 中未找到任务: {task_id}")
            return EXIT_TASK_NOT_FOUND

        if job.next_run_time is None:
            logger.error(f"任务已禁用，拒绝 headless 执行: {task_id}")
            return EXIT_TASK_FAILED

        from scheduler_manager import execute_scheduled_task

        await execute_scheduled_task(**job.kwargs)

        last_status = getattr(worker.task_state, "last_status", "failed")
        logger.info(f"任务执行完成，状态: {last_status}")

        if last_status == "success":
            return EXIT_SUCCESS
        elif last_status == "idle":
            return EXIT_DEVICE_FAILED
        else:
            return EXIT_TASK_FAILED

    except Exception as e:
        logging.getLogger("headless").error(f"Headless 执行异常: {e}", exc_info=True)
        return EXIT_TASK_FAILED
    finally:
        if log_task is not None:
            log_task.cancel()
            with suppress(asyncio.CancelledError):
                await log_task
        if scheduler_manager is not None:
            try:
                await scheduler_manager.shutdown()
            except Exception:
                pass
        if worker is not None:
            try:
                worker.shutdown()
            except Exception:
                pass
        release_runtime_ownership()
        if file_handler is not None:
            try:
                root_logger.removeHandler(file_handler)
                file_handler.close()
            except Exception:
                pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state.is_shutting_down = False
    app_state.worker = MaaWorker(app_state.message_conn, interface, APP_ROOT_DIR)
    app_state.broadcaster = LogBroadcaster()
    with SETTINGS_FILE.open("r", encoding="utf-8") as f:
        config_data = json.load(f)
    with interface_lock:
        app_state.settings = SettingsModel.model_validate(
            config_data,
            context={"interface": interface},
        )
    # 初始化调度器（paused：先 import/repair，再 resume，避免启动期误派发）
    app_state.scheduler_manager = SchedulerManager()
    app_state.scheduler_manager.set_worker(app_state.worker)
    await app_state.scheduler_manager.initialize(paused=True)

    # 初始化系统级调度：将已有 scope 导入 APS，再 repair（均在 paused 下）
    app_state.system_scheduler = SystemTaskService(APP_ROOT_DIR)
    try:
        import_stats = await app_state.system_scheduler.import_scopes_into_aps(
            app_state.scheduler_manager
        )
        # Always surface nonzero failed (e.g. corrupt JSON) before resume.
        if (
            import_stats.get("imported")
            or import_stats.get("failed")
            or import_stats.get("missing_job")
        ):
            detail_tail = ""
            if import_stats.get("failed"):
                details = import_stats.get("details") or []
                detail_tail = f"; details={details}"
            app_state.send_log(
                "系统任务 scope 导入: "
                f"imported={import_stats.get('imported', 0)} "
                f"skipped={import_stats.get('skipped', 0)} "
                f"missing={import_stats.get('missing_job', 0)} "
                f"failed={import_stats.get('failed', 0)}"
                f"{detail_tail}"
            )
    except Exception as e:
        # Log and continue: do not lock out the app; still no pre-resume dispatch.
        app_state.send_log(f"系统任务 scope 导入失败: {e}")

    try:
        repair_result = await app_state.system_scheduler.repair_all(
            app_state.scheduler_manager
        )
        if repair_result["repaired"] or repair_result["failed"]:
            detail_tail = ""
            if repair_result.get("failed"):
                details = repair_result.get("details") or []
                detail_tail = f"; details={details}"
            app_state.send_log(
                f"系统任务修复完成: 修复 {repair_result['repaired']} 个, "
                f"失败 {repair_result['failed']} 个"
                f"{detail_tail}"
            )
    except Exception as e:
        app_state.send_log(f"系统任务修复失败: {e}")

    # Resume APS dispatch only after import+repair attempts complete.
    # Failures above are logged; resume still runs to avoid permanent paused lockout.
    if app_state.scheduler_manager.scheduler is not None:
        app_state.scheduler_manager.scheduler.resume()
        app_state.send_log("调度器已恢复派发（paused import/repair 完成）")

    monitor_task = asyncio.create_task(log_monitor())
    webbrowser.open_new("http://127.0.0.1:5566")
    yield
    app_state.is_shutting_down = True
    monitor_task.cancel()
    with suppress(asyncio.CancelledError):
        await monitor_task
    if app_state.worker:
        app_state.worker.shutdown()
    # 关闭调度器
    if app_state.scheduler_manager:
        await app_state.scheduler_manager.shutdown()
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
        if app_state.worker and app_state.worker.device_state.connected:
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
    msg = app_state.worker.device_state.last_device_error or "设备连接失败"
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
    if (
        app_state.worker.device_state.connected
        and not app_state.worker.device.is_connection_alive()
    ):
        app_state.worker.device.reset_connection_state(
            "检测到设备连接已断开，已解除设备与资源锁定"
        )

    return {
        "status": "success",
        "state": {
            "connected": app_state.worker.device_state.connected,
            "configuration_locked": app_state.worker.device_state.configuration_locked,
            "controller_name": app_state.worker.device_state.controller_name,
            "resource_name": app_state.worker.device_state.current_resource_name,
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
    # 设置资源
    if app_state.worker is None:
        msg = "Worker未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    if not app_state.worker.device_state.connected:
        msg = "请先连接设备后再选择资源"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        ok = await asyncio.to_thread(app_state.worker.device.set_resource, name)
        if not ok:
            msg = app_state.worker.device_state.last_resource_error or "设置资源失败"
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
    try:
        if app_state.update_info is None:
            msg = "暂无可用更新信息"
            app_state.send_log(msg)
            return {"status": "failed", "message": msg}

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
                    msg = f"启动更新器失败: {e}"
                    app_state.send_log(msg)
                    app_state.update_status = {
                        "status": "failed",
                        "message": msg,
                    }
                    break

                process.wait()

                if process.returncode == 10:
                    app_state.update_status = {
                        "status": "updating",
                        "message": "更新器自更新完成，正在重启更新器...",
                    }
                    continue
                else:
                    if process.returncode != 0:
                        msg = f"更新器异常退出: {process.returncode}，请查看updater.log"
                        app_state.send_log(msg)
                        app_state.update_status = {
                            "status": "failed",
                            "message": msg,
                        }
                    break

        threading.Thread(target=run_updater_loop, daemon=True).start()
        return {"status": "success", "message": "正在后台更新程序..."}
    except Exception as e:
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
def start(task_execution: TaskExecutionPayload):
    if app_state.worker is None:
        msg = "Worker未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    if app_state.worker.task_state.running:
        msg = "任务已开始"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    if not app_state.worker.device_state.connected:
        msg = "请先连接设备"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    normalized_task_list, normalized_task_options, normalized_pre_tasks = (
        normalize_task_execution_payload(
            task_execution.task_list,
            task_execution.task_options,
            interface,
            task_execution.preTasks,
        )
    )

    if not normalized_task_list:
        msg = "请选择任务"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}

    if not app_state.worker.tasks.start(
        normalized_task_list,
        normalized_task_options,
        pre_tasks=normalized_pre_tasks,
    ):
        msg = (
            app_state.worker.device_state.last_resource_error
            or app_state.worker.device_state.last_device_error
            or app_state.worker.agent_state.start_error
            or app_state.worker.task_state.last_error
            or "任务启动失败"
        )
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    return {"status": "success"}


@app.post("/api/stop")
def stop():
    if app_state.worker is None or not app_state.worker.task_state.running:
        msg = "任务未开始"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    app_state.worker.tasks.stop()
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
    """创建定时任务"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        if app_state.system_scheduler is not None:
            task = await app_state.system_scheduler.create_task_synced(
                app_state.scheduler_manager, task_create
            )
        else:
            task = await app_state.scheduler_manager.create_task(task_create)
        return {"status": "success", "task": task.model_dump()}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"创建调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.put("/api/scheduler/tasks/{task_id}")
async def update_scheduler_task(task_id: str, task_update: ScheduledTaskUpdate):
    """更新定时任务.

    APS success + native failure returns status=success with additive
    native_status / native_error fields (partial success).
    """
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        if app_state.system_scheduler is not None:
            result = await app_state.system_scheduler.update_task_synced(
                app_state.scheduler_manager, task_id, task_update
            )
            if result.aps_outcome == "not_found" or result.task is None:
                msg = result.aps_error or "任务不存在"
                app_state.send_log(msg)
                return {"status": "failed", "message": msg}
            if result.aps_outcome == "error":
                msg = result.aps_error or "APS 更新失败"
                app_state.send_log(msg)
                return {"status": "failed", "message": msg}
            payload = {
                "status": "success",
                "task": result.task.model_dump(),
            }
            if result.native_status is not None:
                payload["native_status"] = result.native_status.model_dump(mode="json")
            if result.native_error:
                payload["native_error"] = result.native_error
            return payload
        task = await app_state.scheduler_manager.update_task(task_id, task_update)
        if task is None:
            msg = "任务不存在"
            app_state.send_log(msg)
            return {"status": "failed", "message": msg}
        return {"status": "success", "task": task.model_dump()}
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
        if app_state.system_scheduler is not None:
            success = await app_state.system_scheduler.delete_task_synced(
                app_state.scheduler_manager, task_id
            )
        else:
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
    """获取执行历史"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        executions = await app_state.scheduler_manager.get_executions(limit)
        return {
            "status": "success",
            "executions": [exec.model_dump() for exec in executions],
        }
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"获取调度执行历史失败: {msg}")
        return {"status": "failed", "message": msg}


# ---------------------------------------------------------------------------
# 系统级计划任务注册 API
# ---------------------------------------------------------------------------


@app.get("/api/scheduler/system-capabilities")
async def get_system_capabilities():
    """Authoritative capability matrix for native registration."""
    if app_state.system_scheduler is None:
        return {"status": "failed", "message": "系统调度服务未初始化"}
    try:
        caps = app_state.system_scheduler.get_capabilities()
        return {"status": "success", "data": caps.model_dump(mode="json")}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.get("/api/scheduler/tasks/{task_id}/system-status")
async def get_system_task_status(task_id: str):
    """查询任务的系统级注册状态（name/trigger/path from APS when available）"""
    if app_state.system_scheduler is None:
        return {"status": "failed", "message": "系统调度服务未初始化"}

    try:
        status = await app_state.system_scheduler.get_status(
            task_id, manager=app_state.scheduler_manager
        )
        return {"status": "success", "data": status.model_dump(mode="json")}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"查询系统级状态失败: {msg}")
        return {"status": "failed", "message": msg}


@app.get("/api/scheduler/system-tasks")
async def list_system_tasks():
    """列出所有系统级注册的任务（hydrated from APS when available）"""
    if app_state.system_scheduler is None:
        return {"status": "failed", "message": "系统调度服务未初始化"}

    try:
        registrations = await app_state.system_scheduler.list_registered(
            manager=app_state.scheduler_manager
        )
        return {
            "status": "success",
            "registrations": [reg.model_dump(mode="json") for reg in registrations],
        }
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"获取系统级任务列表失败: {msg}")
        return {"status": "failed", "message": msg}


@app.post("/api/scheduler/system-tasks/repair")
async def repair_system_tasks():
    """手动触发修复所有系统级注册（路径变化后使用）"""
    if app_state.system_scheduler is None:
        return {"status": "failed", "message": "系统调度服务未初始化"}
    if app_state.scheduler_manager is None:
        return {"status": "failed", "message": "调度器未初始化"}

    try:
        result = await app_state.system_scheduler.repair_all(
            app_state.scheduler_manager
        )
        return {"status": "success", "data": result}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"修复系统级任务失败: {msg}")
        return {"status": "failed", "message": msg}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MWU - MaaFramework WebUI")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Headless 模式，不启动 Web 服务器（用于系统级调度）",
    )
    parser.add_argument(
        "--task",
        type=str,
        default=None,
        help="要执行的任务 ID（需配合 --headless 使用）",
    )
    args = parser.parse_args()

    if args.headless:
        if not args.task:
            print("错误：--headless 模式需要指定 --task <task_id>")
            sys.exit(EXIT_TASK_FAILED)
        exit_code = asyncio.run(run_headless(args.task))
        sys.exit(exit_code)
    else:
        # Acquire runtime ownership for GUI process lifetime (not on import)
        try:
            app_state.runtime_ownership = acquire_runtime_ownership()
        except LockBusyError as e:
            msg = str(e).lower()
            if "update" in msg:
                print("更新进行中，无法启动")
                sys.exit(EXIT_UPDATING)
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
