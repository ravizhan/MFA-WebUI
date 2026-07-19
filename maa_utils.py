from __future__ import annotations

import io
from typing import TYPE_CHECKING

import httpx
from PIL import Image
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

from maa_worker.agent_service import AgentService
from maa_worker.device_service import DeviceService
from maa_worker.event_service import EventService
from maa_worker.pipeline_override import PipelineOverrideService
from maa_worker.sink_service import SinkHandler, SinkService
from maa_worker.task_service import TaskService
from models.interface import InterfaceModel

if TYPE_CHECKING:
    from app_state import AppState


class MaaWorker:
    def __init__(self, state: AppState, interface: InterfaceModel):
        Toolkit.init_option(str(state.context.interface_base_dir))

        self.state = state
        self.interface = interface
        self.resource = Resource()
        self.resource.set_cpu()
        self.tasker = Tasker()
        self.http_client = httpx.Client(timeout=30)

        self.events = EventService(self)
        self.device = DeviceService(self)
        self.pipeline = PipelineOverrideService(self)
        self.agents = AgentService(self)
        self.tasks = TaskService(self)

        self._sink_handler = SinkHandler(self)
        self.sinks = SinkService(self._sink_handler)
        self.sinks.register_all(self.resource, self.tasker)

        self.events.send_log("MAA初始化成功")

    def get_screencap_bytes(self):
        controller = self.state.device.controller
        if not self.state.device.connected or controller is None:
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
        # Stop running pipeline before tearing down sinks/agents.
        if self.state.task.running:
            try:
                self.tasks.stop()
            except Exception:
                pass
        self.sinks.unregister_all(
            self.resource,
            self.tasker,
            controller=self.state.device.controller,
        )
        if self.state.agent.agent_client is not None:
            self.state.agent.agent_client.disconnect()
        for process in self.state.agent.processes:
            process.terminate()
        self.http_client.close()
