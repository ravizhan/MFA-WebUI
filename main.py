import asyncio
import json
import threading
import webbrowser
from contextlib import asynccontextmanager
from queue import SimpleQueue
import uvicorn
import os
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from models.interface import InterfaceModel
from models.api import DeviceModel, UserConfig
from models.settings import SettingsModel
from maa_utils import MaaWorker
import httpx

with open("interface.json", "r", encoding="utf-8") as f:
    json_data = json.load(f)

interface = InterfaceModel(**json_data)


class LogBroadcaster:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def add_client(self, history: list[str]) -> asyncio.Queue:
        q = asyncio.Queue()
        for msg in history:
            q.put_nowait(msg)
        self._queues.append(q)
        return q

    def remove_client(self, q: asyncio.Queue):
        if q in self._queues:
            self._queues.remove(q)

    async def broadcast(self, message: str):
        for q in self._queues:
            await q.put(message)


class AppState:
    def __init__(self):
        self.message_conn = SimpleQueue()
        self.child_process = None
        self.worker: MaaWorker | None = None
        self.history_message = []
        self.current_status = None
        self.broadcaster: LogBroadcaster | None = None


app_state = AppState()

async def log_monitor():
    while True:
        while not app_state.message_conn.empty():
            msg = app_state.message_conn.get_nowait()
            app_state.history_message.append(msg)
            if app_state.broadcaster:
                await app_state.broadcaster.broadcast(msg)
            
            if "所有任务完成" in msg:
                if app_state.child_process:
                    app_state.child_process.join()
                    app_state.child_process = None
        
        await asyncio.sleep(0.1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    webbrowser.open_new("http://127.0.0.1:55666")
    app_state.worker = MaaWorker(app_state.message_conn, interface)
    app_state.broadcaster = LogBroadcaster()
    monitor_task = asyncio.create_task(log_monitor())
    yield
    monitor_task.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory="page/assets"))
app.mount("/resource", StaticFiles(directory="resource"))

@app.middleware("http")
async def spa_middleware(request: Request, call_next):
    response = await call_next(request)
    if response.status_code == 404 and not ( request.url.path.startswith("/api/") or request.url.path.startswith("/assets/") or request.url.path.startswith("/resource/")):
        return FileResponse("page/index.html")
    return response

@app.get("/")
async def serve_homepage():
    return FileResponse("page/index.html")


@app.get("/api/interface")
def get_interface():
    return interface.model_dump()


async def video_stream_generator(fps: int = 15):
    fps = max(1, min(60, fps))
    interval = 1.0 / fps
    
    while True:
        if app_state.worker and app_state.worker.connected:
            frame_bytes = await asyncio.to_thread(app_state.worker.get_screencap_bytes)
            if frame_bytes:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                await asyncio.sleep(interval)
                continue
        await asyncio.sleep(0.5)

@app.get("/api/stream/live")
async def stream_live(fps: int = 15):
    return StreamingResponse(video_stream_generator(fps), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/device")
def get_device():
    devices = app_state.worker.get_device()
    return {"status": "success","devices": devices}


@app.post("/api/device")
def connect_device(device: DeviceModel):
    if app_state.worker.connect_device(device):
        return {"status": "success"}
    return {"status": "failed"}


@app.get("/api/resource")
def get_resource():
    return {"status": "success","resource":[i.name for i in interface.resource]}

@app.post("/api/resource")
def set_resource(name: str):
    # 设置资源
    try:
        app_state.worker.set_resource(name)
    except Exception as e:
        return {"status": "failed", "message": str(e)}
    return {"status": "success"}

@app.get("/api/settings")
def get_settings():
    with open("config/settings.json", "r", encoding="utf-8") as f:
        config_data = json.load(f)
    settings = SettingsModel(**config_data)
    return {"status": "success", "settings": settings.model_dump()}

@app.post("/api/settings")
def set_settings(settings: SettingsModel):
    with open("config/settings.json", "w", encoding="utf-8") as f:
        json.dump(settings.model_dump(), f, indent=4, ensure_ascii=False)
    return {"status": "success"}


@app.get("/api/user-config")
def get_user_config():
    try:
        with open("config/user_config.json", "r", encoding="utf-8") as f:
            config_data = json.load(f)
        user_config = UserConfig(**config_data)
        return {"status": "success", "config": user_config.model_dump()}
    except FileNotFoundError:
        return {"status": "success", "config": UserConfig().model_dump()}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.post("/api/user-config")
def save_user_config(config: UserConfig):
    try:
        with open("config/user_config.json", "w", encoding="utf-8") as f:
            json.dump(config.model_dump(), f, indent=4, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.delete("/api/user-config")
def reset_user_config():
    try:
        config_path = "config/user_config.json"
        if os.path.exists(config_path):
            os.remove(config_path)
        return {"status": "success"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}
    
@app.get("/api/check-update")
def check_update():
    try:
        repo_name = interface.github.split("/")[3]+"/"+interface.github.split("/")[4]
        response = httpx.get(f"https://api.github.com/repos/{repo_name}/releases/latest").json()
        latest_version = response["tag_name"]
        current_version = interface.version
        update_info = {
            "latest_version": latest_version,
            "current_version": current_version,
            "is_update_available": latest_version != current_version,
            "release_notes": response["body"],
            "download_url": response["html_url"]
        }
        return {"status": "success", "update_info": update_info}
    except Exception as e:
        return {"status": "failed", "message": str(e)}

@app.post("/api/test-notification")
def test_notification():
    if app_state.worker is None:
        return {"status": "failed", "message": "Worker未初始化"}
    try:
        app_state.worker.send_notification("测试通知", "这是一条测试通知。")
        return {"status": "success"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.post("/api/start")
def start(tasks: list[str], options: dict[str, str]):
    if app_state.child_process is not None:
        return {"status": "failed", "message": "任务已开始"}
    if not app_state.worker.connected:
        return {"status": "failed", "message": "请先连接设备"}
    # 设置选项
    for name, case in options.items():
        app_state.worker.set_option(name, case)
    app_state.child_process = threading.Thread(
        target=app_state.worker.run,
        args=(tasks,),
        daemon=True
    )
    app_state.child_process.start()
    return {"status": "success"}


@app.post("/api/stop")
def stop():
    if app_state.child_process is None or app_state.worker is None:
        return {"status": "failed", "message": "任务未开始"}
    app_state.worker.stop_flag = True
    app_state.child_process = None
    return {"status": "success"}


@app.get("/api/logs")
async def stream_logs(request: Request):
    q = app_state.broadcaster.add_client(app_state.history_message)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {json.dumps({'type': 'log', 'message': data}, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            app_state.broadcaster.remove_client(q)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*"
        }
    )


if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=55666)
