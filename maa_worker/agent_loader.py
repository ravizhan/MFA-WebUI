import importlib.abc
import importlib.util
import os
import re
import subprocess
import sys
import traceback
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from maa.resource import Resource


def _cleanup_agent_processes(
    agent_processes: list[subprocess.Popen],
    send_log: Callable[[str], None],
) -> None:
    for process in agent_processes:
        try:
            if process.poll() is not None:
                continue
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        except Exception as e:
            send_log(f"Agent进程回收失败(pid={process.pid}): {e}")


class _BlackMagicAgentServer:
    """黑魔法导入用的 AgentServer 替身，保留装饰器语义但不触发真实注册。"""

    @staticmethod
    def _noop_decorator():
        def wrapper(*args, **kwargs):
            def decorator(target):
                return target

            return decorator

        return wrapper

    custom_action = _noop_decorator.__func__()
    custom_recognition = _noop_decorator.__func__()
    resource_sink = _noop_decorator.__func__()
    controller_sink = _noop_decorator.__func__()
    tasker_sink = _noop_decorator.__func__()
    context_sink = _noop_decorator.__func__()

    @staticmethod
    def register_custom_action(*args, **kwargs) -> bool:
        return True

    @staticmethod
    def register_custom_recognition(*args, **kwargs) -> bool:
        return True

    @staticmethod
    def add_resource_sink(*args, **kwargs) -> None:
        return None

    @staticmethod
    def add_controller_sink(*args, **kwargs) -> None:
        return None

    @staticmethod
    def add_tasker_sink(*args, **kwargs) -> None:
        return None

    @staticmethod
    def add_context_sink(*args, **kwargs) -> None:
        return None

    @staticmethod
    def start_up(*args, **kwargs) -> bool:
        return True

    @staticmethod
    def join(*args, **kwargs) -> None:
        return None

    @staticmethod
    def shut_down(*args, **kwargs) -> None:
        return None

    @staticmethod
    def detach(*args, **kwargs) -> None:
        return None


@contextmanager
def _black_magic_agent_server_stub():
    """
    临时注入 maa.agent / maa.agent.agent_server 的 stub，
    防止导入 AgentServer 时把全局 Library 切到 agent_server 模式。
    """
    maa_module = importlib.import_module("maa")
    saved_modules = {
        name: sys.modules.get(name) for name in ("maa.agent", "maa.agent.agent_server")
    }
    had_agent_attr = hasattr(maa_module, "agent")
    saved_agent_attr = getattr(maa_module, "agent", None)

    stub_agent_module = types.ModuleType("maa.agent")
    stub_agent_module.__package__ = "maa.agent"
    stub_agent_module.__path__ = []

    stub_agent_server_module = types.ModuleType("maa.agent.agent_server")
    stub_agent_server_module.__package__ = "maa.agent"
    stub_agent_server_module.AgentServer = _BlackMagicAgentServer

    stub_agent_module.agent_server = stub_agent_server_module

    sys.modules["maa.agent"] = stub_agent_module
    sys.modules["maa.agent.agent_server"] = stub_agent_server_module
    setattr(maa_module, "agent", stub_agent_module)

    try:
        yield
    finally:
        for name, saved in saved_modules.items():
            if saved is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved

        if had_agent_attr:
            setattr(maa_module, "agent", saved_agent_attr)
        else:
            delattr(maa_module, "agent")


def run_black_magic(agent_config: Any, resource: Resource):
    """
    将Agent转换为custom的黑魔法
    动态加载并注册自定义 Action 和 Recognition
    """
    agent_index_path = next(
        (
            Path(arg.replace("{PROJECT_DIR}", "./")).resolve().parent
            for arg in (agent_config.child_args or [])
            if arg.endswith(".py")
        ),
        None,
    )
    assert agent_index_path is not None, "Agent解析错误，无法找到Agent文件夹"

    # 将agent目录添加到sys.path的开头，确保优先级最高
    if str(agent_index_path) not in sys.path:
        sys.path.insert(0, str(agent_index_path))
        sys.path.insert(1, str(Path("./deps").resolve()))

    # 扫描所有 .py 文件建立映射
    module_map = {}  # module_name -> {path, is_pkg}
    for file_path in agent_index_path.glob("**/*.py"):
        try:
            relative_path = file_path.relative_to(agent_index_path)
            if file_path.name == "__init__.py":
                module_name = (
                    str(relative_path.parent).replace(os.sep, ".").replace("/", ".")
                )
                if module_name in {"", "."}:
                    continue
                is_pkg = True
            else:
                module_name = (
                    str(relative_path.with_suffix(""))
                    .replace(os.sep, ".")
                    .replace("/", ".")
                )
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
                    submodule_search_locations=[os.path.dirname(record["path"])],
                )
            return importlib.util.spec_from_file_location(
                fullname, record["path"], loader=self
            )

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            record = self.mapping[module.__name__]
            file_path = record["path"]
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()

            module.__file__ = file_path
            module.__loader__ = self
            if record["is_pkg"]:
                module.__package__ = module.__name__
                module.__path__ = [os.path.dirname(file_path)]
            else:
                module.__package__ = module.__name__.rpartition(".")[0]

            exec(compile(source, file_path, "exec"), module.__dict__)

    loader = AgentLoader(module_map)
    sys.meta_path.insert(0, loader)

    # 收集需要注册的 Action 和 Recognition
    custom_action_pattern = re.compile(r"@AgentServer.custom_action\(\".*\"\)")
    custom_recognition_pattern = re.compile(
        r"@AgentServer.custom_recognition\(\".*\"\)"
    )
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
                    name = line.split('("')[1].split('")')[0]
                    if i + 1 < len(lines):
                        class_line = lines[i + 1].strip()
                        if class_line.startswith("class "):
                            class_name = (
                                class_line.split("class ")[1]
                                .split("(")[0]
                                .strip()
                                .split(":")[0]
                            )
                            key = "action" if match_action else "recognition"
                            to_register[key].append(
                                {
                                    "name": name,
                                    "class_name": class_name,
                                    "module_name": module_name,
                                }
                            )
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")

    try:
        with _black_magic_agent_server_stub():
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
                                resource.register_custom_recognition(
                                    item["name"], instance
                                )
                    except Exception as e:
                        print(
                            f"Warning: Failed to register {key} '{item['name']}': {e}"
                        )
                        traceback.print_exc()
    finally:
        # 确保清理 loader，避免污染全局导入链
        if loader in sys.meta_path:
            sys.meta_path.remove(loader)


def load_agents(
    agent_configs: list[Any],
    resource: Resource,
    send_log: Callable[[str], None],
    pi_env: dict[str, str] | None = None,
) -> tuple[subprocess.Popen | None, list[subprocess.Popen]]:
    agent_process: subprocess.Popen | None = None
    agent_processes: list[subprocess.Popen] = []
    errors: list[str] = []

    if not agent_configs:
        return agent_process, agent_processes
    for agent_config in agent_configs:
        if "python" in agent_config.child_exec:
            assert agent_config.child_args, "Agent解析错误，缺少child_args"
            try:
                if pi_env:
                    os.environ.update(pi_env)
                run_black_magic(agent_config, resource)
            except Exception as e:
                send_log("黑魔法爆炸了！")
                send_log(f"自定义Agent加载失败: {e}")
                errors.append(f"自定义Agent加载失败: {e}")
                traceback.print_exc()
        else:
            command = [agent_config.child_exec]
            if agent_config.child_args:
                command += agent_config.child_args
            try:
                env = os.environ.copy()
                if pi_env:
                    env.update(pi_env)
                agent_process = subprocess.Popen(command, env=env)
                agent_processes.append(agent_process)
            except Exception as e:
                agent_process = None
                send_log(f"Agent进程启动失败: {e}")
                errors.append(f"Agent进程启动失败: {e}")
                traceback.print_exc()

    if errors:
        _cleanup_agent_processes(agent_processes, send_log)
        raise RuntimeError("；".join(errors))

    return agent_process, agent_processes
