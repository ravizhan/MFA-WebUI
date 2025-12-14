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
import importlib.abc
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
            if option.type == "select" and option.cases:
                for case in option.cases:
                    if case.name == case_name:
                        resource.override_pipeline(case.pipeline_override)
                        # self.send_log(f"选项 {option_name} 设置为: {case_name}")
                        return
            elif option.type == "input" and option.pipeline_override:
                resource.override_pipeline(option.pipeline_override)
                return

    def load_custom_func(self):
        """
        通用的自定义函数加载器
        使用自定义 Loader 机制，自动处理模块依赖关系、循环导入及装饰器去除
        """
        agent_args = getattr(self.interface, "agent", None)
        assert agent_args and getattr(agent_args, "child_args", None), "Interface agent参数解析错误"
        agent_index_path = next(
            (Path(arg.replace("{PROJECT_DIR}", "./")).resolve().parent
             for arg in agent_args.child_args if arg.endswith(".py")),
            None
        )
        assert agent_index_path is not None, "Interface agent参数解析错误"
        
        # 将agent目录添加到sys.path的开头，确保优先级最高
        if str(agent_index_path) not in sys.path:
            sys.path.insert(0, str(agent_index_path))
        
        # 扫描所有 .py 文件建立映射
        module_map = {}  # module_name -> {path, is_pkg}
        for file_path in agent_index_path.glob("**/*.py"):
            try:
                relative_path = file_path.relative_to(agent_index_path)
                if file_path.name == "__init__.py":
                    module_name = str(relative_path.parent).replace(os.sep, '.').replace('/', '.')
                    if module_name in {"", "."}:
                        continue
                    is_pkg = True
                else:
                    module_name = str(relative_path.with_suffix('')).replace(os.sep, '.').replace('/', '.')
                    is_pkg = False
                if module_name:
                    module_map[module_name] = {"path": str(file_path), "is_pkg": is_pkg}
            except ValueError:
                continue

        # 自定义 Loader，利用 importlib 规范支持循环 / 相互导入
        class AgentLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
            def __init__(self, mapping):
                self.mapping = mapping

            def find_spec(self, fullname, path, target=None):
                if fullname not in self.mapping:
                    return None
                record = self.mapping[fullname]
                if record["is_pkg"]:
                    return importlib.util.spec_from_file_location(
                        fullname,
                        record["path"],
                        loader=self,
                        submodule_search_locations=[os.path.dirname(record["path"])]
                    )
                return importlib.util.spec_from_file_location(fullname, record["path"], loader=self)

            def create_module(self, spec):
                return None

            def exec_module(self, module):
                record = self.mapping[module.__name__]
                file_path = record["path"]
                with open(file_path, "r", encoding="utf-8") as f:
                    source = f.read()

                # 移除 @AgentServer 装饰器，避免注册时重复绑定
                if "@AgentServer" in source:
                    filtered_lines = [line for line in source.split('\n') if "AgentServer" not in line]
                    source = '\n'.join(filtered_lines)

                module.__file__ = file_path
                module.__loader__ = self
                if record["is_pkg"]:
                    module.__package__ = module.__name__
                    module.__path__ = [os.path.dirname(file_path)]
                else:
                    module.__package__ = module.__name__.rpartition('.')[0]

                exec(compile(source, file_path, 'exec'), module.__dict__)

        loader = AgentLoader(module_map)
        sys.meta_path.insert(0, loader)

        # 收集需要注册的 Action 和 Recognition
        custom_action_pattern = re.compile(r"@AgentServer.custom_action\(\".*\"\)")
        custom_recognition_pattern = re.compile(r"@AgentServer.custom_recognition\(\".*\"\)")
        to_register = {"action": [], "recognition": []}

        for module_name, info in module_map.items():
            file_path = info.get("path")
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                
                for i, line in enumerate(lines):
                    match_action = re.match(custom_action_pattern, line.strip())
                    match_recognition = re.match(custom_recognition_pattern, line.strip())
                    
                    if match_action or match_recognition:
                        name = line.split("(\"")[1].split("\")")[0]
                        if i + 1 < len(lines):
                            class_line = lines[i + 1].strip()
                            if class_line.startswith("class "):
                                class_name = class_line.split("class ")[1].split("(")[0].strip().split(":")[0]
                                key = "action" if match_action else "recognition"
                                to_register[key].append({
                                    "name": name,
                                    "class_name": class_name,
                                    "module_name": module_name
                                })
            except Exception as e:
                print(f"Error scanning {file_path}: {e}")

        try:
            # 加载所有模块（支持循环/相互导入）
            for module_name in module_map:
                try:
                    importlib.import_module(module_name)
                except Exception as e:
                    print(f"Warning: Failed to import module {module_name}: {e}")
                    traceback.print_exc()

            # 注册实例
            for key in ["recognition", "action"]:
                for item in to_register[key]:
                    try:
                        module = sys.modules.get(item["module_name"])
                        if module:
                            cls = getattr(module, item["class_name"])
                            instance = cls()
                            if key == "action":
                                resource.register_custom_action(item["name"], instance)
                            else:
                                resource.register_custom_recognition(item["name"], instance)
                    except Exception as e:
                        print(f"Warning: Failed to register {key} '{item['name']}': {e}")
                        traceback.print_exc()
        finally:
            # 确保清理 loader，避免污染全局导入链
            if loader in sys.meta_path:
                sys.meta_path.remove(loader)

    def run(self, task_list):
        self.stop_flag = False
        self.send_log("任务开始")
        try:
            for task in task_list:
                t = self.tasker.post_task(task)
                self.send_log("正在运行任务: " + task)
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
