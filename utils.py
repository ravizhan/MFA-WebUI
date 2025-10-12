import os
import time
import traceback
from queue import SimpleQueue

import plyer
from maa.controller import AdbController
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

resource = Resource()
resource.set_cpu()

class MaaWorker:
    def __init__(self, queue: SimpleQueue, version: int, interface):
        user_path = "./"
        Toolkit.init_option(user_path)
        if version == 2:
            # from models.interfaceV2 import InterfaceModel
            # self.interface: InterfaceModel = interface
            pass
        else:
            from models.interfaceV1 import InterfaceModel
            self.interface: InterfaceModel = interface
        self.queue = queue
        self.tasker = Tasker()
        self.connected = False
        self.stop_flag = False
        self.send_log("MAA初始化成功")

    def send_log(self, msg):
        self.queue.put(f"{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())} {msg}")
        time.sleep(0.05)

    @staticmethod
    def get_device():
        adb_devices = []
        for device in Toolkit.find_adb_devices():
            # 这两个字段的数字在JS里会整数溢出，转为字符串处理
            device.input_methods = str(device.input_methods)
            device.screencap_methods = str(device.screencap_methods)
            if device not in adb_devices:
                adb_devices.append(device)
        return adb_devices

    def connect_device(self, device):
        controller = AdbController(
            adb_path=device.adb_path,
            address=device.address,
            screencap_methods=device.screencap_methods,
            input_methods=device.input_methods,
            config=device.config,
        )
        status = controller.post_connection().wait().succeeded
        conn_fail_msg = "设备连接失败，请检查终端日志"
        if not status:
            plyer.notification.notify(
                title=self.interface.name,
                message=conn_fail_msg,
                app_name=self.interface.name,
                timeout=30
            )
            self.send_log(conn_fail_msg)
            return self.connected
        if self.tasker.bind(resource, controller):
            self.connected = True
            # size = subprocess.run([device.adb_path, "shell", "wm", "size"], text=True, capture_output=True).stdout
            # size = size.strip().split(": ")[1]
            # dpi = subprocess.run([device.adb_path, "shell", "wm", "density"], text=True, capture_output=True).stdout
            # dpi = dpi.strip().split(": ")[1]
            # print(size,dpi)
            self.send_log("设备连接成功")
        else:
            plyer.notification.notify(
                title=self.interface.name,
                message=conn_fail_msg,
                app_name=self.interface.name,
                timeout=30
            )
            self.send_log(conn_fail_msg)
        return self.connected

    def set_resource(self, resource_name):
        def replace(path: str):
            return os.path.realpath(path.replace("{PROJECT_DIR}",os.getcwd()))
        for i in self.interface.resource:
            if i.name == resource_name:
                resource.post_bundle(replace(i.path[0])).wait()
                if len(i.path) > 1:
                    resource.post_bundle(replace(i.path[1])).wait()
                self.send_log(f"资源已设置为: {i.name}")
        return None

    def set_option(self, option_name: str, case_name: str):
        if option_name in self.interface.option:
            option = self.interface.option[option_name]
            for case in option.cases:
                if case.name == case_name:
                    resource.override_pipeline(case.pipeline_override)
                    # self.send_log(f"选项 {option_name} 设置为: {case_name}")
                    return

    def run(self, task_list):
        self.stop_flag = False
        self.send_log("任务开始")
        try:
            for task in task_list:
                t = self.tasker.post_task(task)
                while not t.done:
                    time.sleep(0.5)
                    if self.stop_flag:
                        self.tasker.post_stop().wait()
                        self.send_log("任务已终止")
                        return
        except Exception:
            traceback.print_exc()
            plyer.notification.notify(
                title=self.interface.name,
                message="任务出现异常，请检查终端日志",
                app_name=self.interface.name,
                timeout=30
            )
            self.send_log("任务出现异常，请检查终端日志")
            self.send_log(f"请将日志反馈至 {self.interface.url}/issues")
        self.send_log("所有任务完成")
        time.sleep(0.5)
