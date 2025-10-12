import asyncio
import json
import threading
import webbrowser
from contextlib import asynccontextmanager
from queue import SimpleQueue
import uvicorn

from fastapi import FastAPI, websockets
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState, WebSocketDisconnect

from models.api import DeviceModel
from utils import MaaWorker

with open("interface.json", "r", encoding="utf-8") as f:
    json_data = json.load(f)
if json_data.get("interface_version") == "2":
    # from models.interfaceV2 import InterfaceModel
    INTERFACE_VERSION = 2
    pass
else:
    INTERFACE_VERSION = 1
    from models.interfaceV1 import InterfaceModel
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
    app_state.worker = MaaWorker(app_state.message_conn, INTERFACE_VERSION, interface)
    await asyncio.sleep(1.0)
    webbrowser.open_new("http://127.0.0.1:55666")
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory="page/assets"))


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
