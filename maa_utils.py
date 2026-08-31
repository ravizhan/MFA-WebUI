import io
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from PIL import Image

from app_state import WorkerContext
from maa_worker.agent_service import AgentService
from maa_worker.device_service import DeviceService
from maa_worker.event_service import EventService
from maa_worker.pipeline_override import PipelineOverrideService
from maa_worker.pretask_service import PretaskService
from maa_worker.sink_service import SinkHandler, SinkService
from maa_worker.task_service import TaskService
from models.interface import InterfaceModel

if TYPE_CHECKING:
    from app_state import AppState

resource = Resource()
resource.set_cpu()


class MaaWorker:
    def __init__(
        self,
        state: "AppState",
        interface: InterfaceModel,
    ):
        self.state = state
        self.interface = interface
        self.message_conn = state.message_conn
        self.resource = resource
        self.tasker = Tasker()
        self.http_client = httpx.Client(timeout=30)

        # 运行时状态并入 AppState（单例）
        state.context = WorkerContext(interface_base_dir=self._resolve_app_root())
        self.context = state.context
        self.device_state = state.device
        self.task_state = state.task
        self.agent_state = state.agent

        Toolkit.init_option(str(self.context.interface_base_dir))

        self.events = EventService(self)
        self.device = DeviceService(self)
        self.pipeline = PipelineOverrideService(self)
        self.agents = AgentService(self)
        self.pretasks = PretaskService(self)
        self.tasks = TaskService(self)

        self._sink_handler = SinkHandler(self)
        self.sinks = SinkService(self._sink_handler)
        self.sinks.register_all(self.resource, self.tasker)

        self.events.send_log("MAA初始化成功")

    @staticmethod
    def _resolve_app_root() -> Path:
        import sys

        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    def get_screencap_bytes(self):
        controller = self.device_state.controller
        if not self.device_state.connected or controller is None:
            return None
        try:
            image = controller.post_screencap().wait().get()
            if image is not None:
                image_pil = Image.fromarray(image[:, :, ::-1])
                img_byte_arr = io.BytesIO()
                image_pil.save(img_byte_arr, format="JPEG")
                return img_byte_arr.getvalue()
        except Exception:
            self.device.reset_connection_state(
                "检测到设备连接已断开，已解除设备与资源锁定"
            )
        return None

    def shutdown(self):
        if self.task_state.running:
            self.tasks.stop()
        else:
            # 前置任务阶段 running 尚未置位：兜底置停止标志并终止正在运行的前置进程，
            # 避免关闭/更新时用户前置命令一直阻塞到超时。
            self.task_state.stop_flag = True
            self.pretasks.stop_current()
        self.sinks.unregister_all(
            self.resource,
            self.tasker,
            controller=self.device_state.controller,
        )
        if self.agent_state.agent_client is not None:
            self.agent_state.agent_client.disconnect()
        for process in self.agent_state.processes:
            process.terminate()
        self.http_client.close()
