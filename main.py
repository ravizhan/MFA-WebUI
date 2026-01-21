import asyncio
import json
import threading
import webbrowser
from contextlib import asynccontextmanager
from queue import SimpleQueue
import uvicorn
import os
from fastapi import FastAPI, websockets, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState, WebSocketDisconnect
from models.interfaceV2 import InterfaceModel
from models.api import DeviceModel, UserConfig
from models.settings import SettingsModel
from maa_utils import MaaWorker

with open("interface.json", "r", encoding="utf-8") as f:
    json_data = json.load(f)

interface = InterfaceModel(**json_data)


class AppState:
    def __init__(self):
        self.message_conn = SimpleQueue()
        self.child_process = None
        self.worker: MaaWorker | None = None
        self.history_message = []
        self.current_status = None


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    webbrowser.open_new("http://127.0.0.1:55666")
    app_state.worker = MaaWorker(app_state.message_conn, interface)
    yield


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


@app.websocket("/api/ws")
async def websocket_endpoint(websocket: websockets.WebSocket):
    await websocket.accept()
    last_ping = asyncio.create_task(asyncio.sleep(0))
    try:
        await asyncio.sleep(0.5)
        for msg in app_state.history_message:
            await websocket.send_text(msg)
        while websocket.client_state == WebSocketState.CONNECTED:
            if not app_state.message_conn.empty():
                data = app_state.message_conn.get_nowait()
                app_state.history_message.append(data)
                if "所有任务完成" in data:
                    app_state.child_process.join()
                    # 重置状态
                    app_state.child_process = None
                    await websocket.send_text(data)
                    continue
                await websocket.send_text(data)
            if last_ping.done():
                last_ping = asyncio.create_task(asyncio.sleep(5))
                await websocket.send_text("ping")
            await asyncio.sleep(0.01)
    except WebSocketDisconnect:
        print("WebSocket disconnect")
        last_ping.cancel()
    finally:
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except RuntimeError:
                pass


if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=55666)
