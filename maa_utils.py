import os
import time
import traceback
from queue import SimpleQueue

import plyer
from maa.controller import AdbController
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
import importlib.util
import re
import sys
from pathlib import Path

resource = Resource()
resource.set_cpu()

class MaaWorker:
    def __init__(self, queue: SimpleQueue, interface):
        Toolkit.init_option("./")
        from models.interfaceV2 import InterfaceModel
        self.interface: InterfaceModel = interface
        self.queue = queue
        self.tasker = Tasker()
        self.connected = False
        self.stop_flag = False
        self.send_log("MAA初始化成功")
        self.load_custom_func()
        self.send_log("Agent加载完成")

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
                title=self.interface.title,
                message=conn_fail_msg,
                app_name=self.interface.label,
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
                title=self.interface.title,
                message=conn_fail_msg,
                app_name=self.interface.label,
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

    def load_custom_func(self):
        def load_module(module_path):
            # 1. 读取模块源代码
            with open(module_path, "r", encoding="utf-8") as f:
                source = f.read()
            # 2. 删除装饰器行
            filtered_lines = [line for line in source.split('\n') if "AgentServer" not in line]
            modified_source = '\n'.join(filtered_lines)
            # 3. 创建模块对象
            spec = importlib.util.spec_from_file_location("temp_module", module_path)
            module = importlib.util.module_from_spec(spec)
            # 4. 执行模块代码
            exec(modified_source, module.__dict__)
            return module

        agent_index_path = next(
            (Path(arg.replace("{PROJECT_DIR}", "./")).resolve().parent
             for arg in self.interface.agent.child_args if arg.endswith(".py")),
            None
        )
        assert agent_index_path is not None, "Interface agent参数解析错误"
        sys.path.append(str(agent_index_path))
        custom_action_pattern = re.compile(r"@AgentServer.custom_action\(\".*\"\)")
        custom_recognition_pattern = re.compile(r"@AgentServer.custom_recognition\(\".*\"\)")
        custom = {
            "action": [],
            "recognition": [],
        }

        for file in agent_index_path.glob("**/*.py"):
            if file.name == "__init__.py":
                sys.path.append(str(file.parent))
                continue
            with open(file, "r", encoding="utf-8") as f:
                file_lines = f.readlines()
            for line in file_lines:
                match_action = re.match(custom_action_pattern, line.strip())
                match_recognition = re.match(custom_recognition_pattern, line.strip())

                if match_action or match_recognition:
                    name = line.split("(\"")[1].split("\")")[0]
                    class_line = file_lines[file_lines.index(line) + 1].strip()
                    class_name = class_line.split("class ")[1].split("(")[0]
                    key = "action" if match_action else "recognition"
                    custom[key].append({"name": name, "class": class_name, "file_path": str(file)})

        for action in custom["action"]:
                module = load_module(action["file_path"])
                instance = getattr(module, action["class"])()
                resource.register_custom_action(action["name"], instance)
        for recognition in custom["recognition"]:
            module = load_module(recognition["file_path"])
            instance = getattr(module, recognition["class"])()
            resource.register_custom_recognition(recognition["name"], instance)

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
                title=self.interface.title,
                message="任务出现异常，请检查终端日志",
                app_name=self.interface.label,
                timeout=30
            )
            self.send_log("任务出现异常，请检查终端日志")
            self.send_log(f"请将日志反馈至 {self.interface.github}/issues")
        self.send_log("所有任务完成")
        time.sleep(0.5)
