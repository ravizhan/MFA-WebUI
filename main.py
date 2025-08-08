import asyncio
import json
import threading
import webbrowser
from contextlib import asynccontextmanager
from queue import SimpleQueue

from fastapi import FastAPI, websockets
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from models import InterfaceModel, DeviceModel, PostTaskModel
from utils import MaaWorker

with open("interface.json", "r", encoding="utf-8") as f:
    json_data = json.load(f)
interface = InterfaceModel(**json_data)


class AppState:
    def __init__(self):
        self.message_conn = SimpleQueue()
        self.child_process = None
        self.worker = None
        self.history_message = []
        self.current_status = None


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state.worker = MaaWorker(app_state.message_conn)
    webbrowser.open_new("http://127.0.0.1:55666")
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory="page/assets"))


@app.get("/")
async def serve_homepage():
    return FileResponse("page/index.html")


@app.get("/api/info")
def get_info():
    data = {
        "basic": {
            "name": interface.name,
            "version": interface.version,
            "url": interface.url
        },
        "settings": {
            "resource": interface.resource
        }
    }
    return data


@app.get("/api/get_device")
def get_device():
    if app_state.worker is None:
        return {"status": "failed", "message": "MAA未初始化，请先保存设置"}
    devices = app_state.worker.get_device()
    return {"devices": devices}


@app.post("/api/connect_device")
def connect_device(device: DeviceModel):
    if app_state.worker.connect_device(device):
        return {"status": "success"}
    return {"status": "failed"}


@app.post("/api/start")
def start(tasks: PostTaskModel):
    if app_state.worker is None:
        return {"status": "failed", "message": "MAA未初始化，请先保存设置"}
    if app_state.child_process is not None:
        return {"status": "failed", "message": "任务已开始"}
    if not app_state.worker.connected:
        return {"status": "failed", "message": "请先连接设备"}
    app_state.child_process = threading.Thread(
        target=app_state.worker.task,
        args=(tasks.tasklist,),
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


@app.post("/api/continue")
def going_on():
    app_state.worker.pause_flag = False
    return {"status": "success"}


@app.websocket("/api/ws")
async def websocket_endpoint(websocket: websockets.WebSocket):
    await websocket.accept()
    if app_state.history_message:
        for i in app_state.history_message:
            await websocket.send_text(i)
    while True:
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
        await asyncio.sleep(0.01)


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=55666)
