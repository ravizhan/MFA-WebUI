<!-- markdownlint-disable MD033 MD041 -->

<p align="center">
  <img alt="LOGO" src="https://github.com/ravizhan/MWU/blob/main/logo.jpg" width="256" height="256" />
</p>

<div align="center">

# MWU

<!-- prettier-ignore-start -->
<!-- markdownlint-disable-next-line MD036 -->
_✨ 基于 **[Vue](https://github.com/vuejs/vue)** 和 **[FastAPI](https://github.com/fastapi/fastapi)**  的 **[MAAFramework](https://github.com/MaaXYZ/MaaFramework)** 通用 WebUI 项目 ✨_

**本项目尚未Production-Ready，欢迎测试并提供反馈**
<!-- prettier-ignore-end -->

  <img alt="license" src="https://img.shields.io/github/license/ravizhan/MWU">
  <img alt="Python" src="https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fravizhan%2FMWU%2Frefs%2Fheads%2Fmain%2Fpyproject.toml">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blueviolet">
  <img alt="commit" src="https://img.shields.io/github/commit-activity/m/ravizhan/MWU">
  <img alt="stars" src="https://img.shields.io/github/stars/ravizhan/MWU?style=social">
  <a href="https://deepwiki.com/ravizhan/MWU" target="_blank"><img alt="deepwiki" src="https://deepwiki.com/badge.svg"></a>
</div>

## ✨ 项目特点

- 🚀 **现代化技术栈** - 前后端分离架构，Vue 3 + FastAPI
- 🎨 **美观易用** - 基于 NaiveUI 组件库，界面简洁美观，支持深色模式自动切换
- 🔌 **魔改 Agent 实现** - 通过动态解析导入，无需额外 Python 环境
- 🔧 **高度可定制** - Python 代码简洁易修改，轻松实现各种定制需求
- 🔔 **系统通知** - 依托 Plyer 和浏览器API实现跨平台双渠道系统通知
- 🔄 **自动更新** - 支持 GitHub 自动下载更新
- 📱 **跨平台兼容** - Windows / Linux / macOS 全平台支持，基于浏览器提供统一的用户体验
- ⚡ **开箱即用** - 强兼官方模板，极致简单的步骤，快速接入
- 🎯 **弃繁从简** - 抛弃一切不必要的组件，提供尽可能小巧的体积

## 📋 环境需求

| 组件       | 要求                                                   |
| ---------- | :----------------------------------------------------- |
| **系统**   | Windows 10+、Linux、macOS                              |
| **资源**   | 基于 MaaFramework 的资源项目                           |
| **浏览器** | Chrome >=111；Edge >=111；Firefox >=114；Safari >=16.4 |

## 🚀 快速开始

> 请先阅读[MaaFW文档](https://maafw.com/docs/1.1-QuickStarted)，选择一种集成方案

如果您选择低代码或低代码+Agent方案，只需按照指引使用 [MaaFramework 项目模板](https://github.com/MaaXYZ/MaaPracticeBoilerplate) 创建项目，然后将其中的 `.github/workflows/install.yml` 替换为本项目的 [deploy/install.yaml](https://github.com/ravizhan/MWU/blob/main/deploy/install.yml) 即可。

如果您选择全代码开发集成，并且也想使用本项目的UI，请继续阅读 [项目架构与开发](https://github.com/ravizhan/MWU#%EF%B8%8F-%E9%A1%B9%E7%9B%AE%E6%9E%B6%E6%9E%84%E4%B8%8E%E5%BC%80%E5%8F%91)

### ⚙️ 配置清单

| 配置         | 默认值                  | 修改方法                                                     |
| ------------ | ----------------------- | ------------------------------------------------------------ |
| 压缩包名     | 仓库名-版本号-平台-架构 | [deploy/install.yml#L170](https://github.com/ravizhan/MWU/blob/baeec32ecc5db8ea6390ceb5575d73e2d2754ba6/deploy/install.yml#L170)，注意下方各处也要一并修改 |
| 可执行文件名 | MWU               | 暂不可修改                                                   |
| LOGO         |                         | 暂不可修改                                                   |

### 📦 额外拓展功能
#### scan_select 选项类型

`scan_select` 用于在加载 `interface.json` 时扫描目录文件，并把扫描结果自动写入当前选项的 `cases`，适用于“配置文件选择”等动态枚举场景。

字段定义如下：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `type` | `"scan_select"` | 是 | 选项类型 |
| `label` | `string` | 否 | 前端显示名称 |
| `description` | `string` | 否 | 描述信息 |
| `scan_dir` | `string` | 是 | 扫描目录。相对路径基于 interface.json 所在目录解析，并做越界限制（不允许跳出该目录） |
| `scan_filter` | `string` | 是 | `glob pattern`，用于筛选文件，如 `**/*.json` |
| `pipeline_override` | `object` | 是 | 任务执行时使用的覆盖配置，须包含 `{option_name}` 占位符 |
| `cases` | `OptionCase[]` | 否（配置阶段应省略或空数组） | 加载时自动生成，`name`/`label` 均为相对 `scan_dir` 的路径+文件名 |
| `default_case` | `string` | 否 | 默认选项名称 |

示例：

加载前：

```json
{
  "option": {
    "bbc_team_config": {
      "type": "scan_select",
      "label": "BBC 队伍配置",
      "description": "选择 BBC 队伍配置文件",
      "scan_dir": "./resource/BBchannel/settings",
      "scan_filter": "**/*.json",
      "pipeline_override": {
        "队伍配置": {
          "custom_action_param": "{bbc_team_config}"
        }
      }
    }
  }
}
```

加载完成且用户选择 `1.json`：
> 该结果仅在内存保留，不会实际修改interface.json

```json
{
  "option": {
    "bbc_team_config": {
      "type": "scan_select",
      "label": "BBC 队伍配置",
      "description": "选择 BBC 队伍配置文件",
      "scan_dir": "./resource/BBchannel/settings",
      "scan_filter": "**/*.json",
      "pipeline_override": {
        "队伍配置": {
          "custom_action_param": "1.json"
        }
      },
      "cases": [
        {
          "name": "1.json",
          "label": "1.json"
        },
        {
          "name": "bbb/c.json",
          "label": "bbb/c.json"
        }
      ]
    }
  }
}
```

## 🏗️ 项目架构与开发

> **如果您需要更多的定制化功能或想为本项目做出贡献，请阅读以下部分**

### 📐 架构概览

项目采用前后端分离架构：

- **后端**：FastAPI (Python 3.12+)，提供 RESTful API 和 Server-Sent Events (SSE) 服务，运行在 `http://127.0.0.1:55666`
- **前端**：Vue 3 + NaiveUI + Vite + UnoCSS + Pinia，构建输出到 `page/` 目录
- **核心交互**：通过 SSE (Server-Sent Events) 实现任务状态和日志的实时推送

### 💻 开发指南

#### 🎨 前端开发

```bash
cd front
pnpm dev     # 开发服务器，自动代理 /api 到 localhost:55666
pnpm build   # 构建到 ../page 目录
pnpm lint    # 使用 oxlint 进行代码检查
pnpm format  # 使用 Prettier 格式化代码
```

#### 🔧 后端开发

```bash
uv run main.py  # 启动 FastAPI 服务
```

**依赖管理**：使用 `uv` 作为 Python 包管理器

#### 🧪 项目构建

``` bash
cd front && pnpm run build   # 前端构建
cd updater && go build       # 更新器构建
uv run python -m nuitka --standalone --assume-yes-for-downloads --user-package-configuration-file=nuitka-package.config.yml --output-dir=build --include-package=PIL --include-package=maa -o MWU main.py # 后端构建
```

#### 📁 项目文件目录

```
MWU/
├── main.py                      # FastAPI 应用入口，自动打开浏览器
├── maa_utils.py                 # MaaWorker 类，处理所有 MAA 框架交互
├── app_state.py                 # 全局应用状态管理
├── scheduler_manager.py         # 定时任务调度管理器
├── interface.json               # 项目接口配置（V2 协议）
│
├── agent/                       # Agent 动态扩展目录
│   ├── main.py                  # Agent 主程序
│   ├── custom/                  # 自定义 Action/Reco/Sink 实现
│   ├── libs/                    # Agent 依赖库
│   └── utils/                   # Agent 工具类
│
├── config/                      # 配置文件目录
│   ├── settings.json            # 应用设置
│   ├── task_config.json         # 任务配置缓存
│   └── maa_option.json          # MAA 选项配置
│
├── models/                      # 数据模型目录
│   ├── api.py                   # API 请求/响应模型
│   ├── interface.py             # interface 数据模型
│   ├── interface_loader.py      # interface 加载逻辑
│   ├── scheduler.py             # 定时任务相关模型
│   ├── settings.py              # 设置数据模型
│   └── task_config.py           # 任务配置模型
│
├── maa_worker/                  # MAA 核心工作进程
│   ├── agent_loader.py          # Agent 动态加载器
│   ├── device_manager.py        # 设备管理器
│   └── task_runner.py           # 任务执行器
│
├── services/                    # 后端业务服务
│   └── update_service.py        # 更新服务实现
│
├── updater/                     # Go 更新器目录
│   ├── main.go                  # 更新器主程序
│   ├── go.mod                   # Go 模块定义
│   └── go.sum                   # Go 依赖校验
│
├── deploy/                      # 部署与 CI 相关脚本
│   ├── install.yml              # GitHub Actions 部署配置
│   ├── download_deps.py         # 依赖下载脚本
│   └── copy_resources.py        # 资源复制脚本
│
├── page/                        # 前端构建输出（FastAPI 静态服务）
│
├── resource/                    # MAA 资源文件目录（base, data, tasks等）
│
└── front/                       # 前端项目目录
    └── src/                     # 源代码目录
        ├── App.vue              # 根组件
        ├── main.ts              # 前端入口文件
        ├── components/          # Vue 组件
        │   ├── LeftPanel.vue    # 左侧任务列表
        │   ├── MediumPanel.vue  # 中间选项面板
        │   ├── RightPanel.vue   # 右侧日志与控制
        │   └── ...              # 其他功能组件
        ├── router/              # Vue Router 路由配置
        ├── theme.ts             # 主题配置
        ├── services/            # API 调用与实时通信实现
        │   ├── api/             # 领域 API (device, task, settings等)
        │   ├── sse.ts           # SSE 客户端实现
        │   └── realtime.ts      # 实时状态同步
        ├── stores/              # Pinia 状态管理 (interface, settings等)
        ├── types/               # TypeScript 类型定义
        ├── views/               # 页面视图 (PanelView, SettingView)
        └── utils/               # 前端工具类
```

### 全代码开发集成

> 以下仅为推荐写法，对于全代码开发，选择权都在于您

#### 📐 关键文件说明

- `main.py`：FastAPI 路由与生命周期管理（启动 `MaaWorker`、调度器、日志流）
- `app_state.py`：运行时状态与日志广播
- `maa_utils.py`：`MaaWorker` 编排层（事件通知、`pipeline_override` 合并、任务入口）
- `maa_worker/device_manager.py`：设备发现、连接、资源加载
- `maa_worker/task_runner.py`：任务线程启动/停止与执行主循环

#### 🔧 扩展任务执行流程

任务执行主循环位于 `maa_worker/task_runner.py` 的 `run_process`。如果您需要“特殊任务分支 + 默认 pipeline 共存”，推荐按下面方式扩展：

```python
# maa_worker/task_runner.py

def run_process(worker, task_list, options):
    try:
        worker._emit_task_started(task_list)
        for task in task_list:
            if worker.stop_flag:
                worker.tasker.post_stop().wait()
                worker.last_task_status = "stopped"
                worker.last_task_error = "任务已终止"
                worker.send_log("任务已终止")
                return

            # 自定义入口：按 task entry 分发到专用逻辑
            if task == "MyCustomEntry":
                if not _run_my_custom_entry(worker, options):
                    return
                continue

            # 默认入口：继续走 interface.json 的 pipeline 任务
            pipeline_override = worker._build_task_pipeline_override(task, options)
            t = (
                worker.tasker.post_task(task, pipeline_override)
                if pipeline_override
                else worker.tasker.post_task(task)
            )
            worker.send_log("正在运行任务: " + task)

            while not t.done:
                time.sleep(0.5)
                if worker.stop_flag:
                    worker.tasker.post_stop().wait()
                    worker.last_task_status = "stopped"
                    worker.last_task_error = "任务已终止"
                    worker.send_log("任务已终止")
                    return

        worker.last_task_status = "success"
        worker.last_task_error = None
        worker._emit_task_completed(task_list)
    except Exception as exc:
        worker.last_task_status = "failed"
        worker.last_task_error = str(exc) or "任务执行失败"
        worker._emit_task_failed(task_list, worker.last_task_error)
        worker.send_log("任务出现异常，请检查终端日志")
    finally:
        worker.running = False
        worker._task_thread = None
        worker._current_task_name = None
        time.sleep(0.5)


def _run_my_custom_entry(worker, options):
    worker.send_log("开始执行自定义任务: MyCustomEntry")
    pipeline_override = worker._build_task_pipeline_override("MyCustomEntry", options)
    t = (
        worker.tasker.post_task("MyCustomEntry", pipeline_override)
        if pipeline_override
        else worker.tasker.post_task("MyCustomEntry")
    )
    while not t.done:
        time.sleep(0.5)
        if worker.stop_flag:
            worker.tasker.post_stop().wait()
            worker.last_task_status = "stopped"
            worker.last_task_error = "任务已终止"
            worker.send_log("任务已终止")
            return False
    worker.send_log("自定义任务执行完成")
    return True
```

#### 📝 自定义 Action 和 Recognition

您可以在 `maa_utils.py` 中添加自定义的 Action 和 Recognition：

```python
# maa_utils.py

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition
from maa.define import TaskDetail
import numpy as np
from PIL import Image


# ========== 自定义 Recognition ==========
@resource.custom_recognition("MyCustomReco")
class MyCustomRecognition(CustomRecognition):
    def analyze(self, context, argv: CustomRecognition.AnalyzeArg):
        """自定义识别逻辑"""
        # 获取当前屏幕图像
        image = context.tasker.controller.post_screencap().wait().get()

        # 您的识别逻辑...
        # 返回识别结果
        return CustomRecognition.AnalyzeResult(
            box=(x, y, w, h),  # 识别框坐标
            detail="识别详情"
        )


# ========== 自定义 Action ==========
@resource.custom_action("MyCustomAction")
class MyCustomAction(CustomAction):
    def run(self, context, argv: CustomAction.RunArg):
        """自定义操作逻辑"""
        # 获取点击坐标
        box = argv.rec_box
        x, y = box[0] + box[2] // 2, box[1] + box[3] // 2

        # 执行点击
        context.tasker.controller.post_click(x, y).wait()

        return CustomAction.RunResult(success=True)
```

#### 💡 开发建议

1. **优先按模块改动**：设备相关优先改 `maa_worker/device_manager.py`，任务流优先改 `maa_worker/task_runner.py`，避免把所有逻辑塞进 `maa_utils.py`。
2. **统一事件出口**：日志与通知尽量走 `MaaWorker.emit_event` / `send_log` / `send_notification`，便于前端 SSE 与通知配置统一生效。
3. **保持任务状态可观测**：自定义流程要维护 `last_task_status` / `last_task_error`，这样定时调度执行记录才能正确展示。
4. **谨慎新增实时事件类型**：若新增事件名，请同步更新后端 `RealtimeEventName` 与前端事件处理逻辑。
5. **避免命名冲突**：不要新建顶层 `utils` 包，避免与 agent 动态加载路径冲突。

## 📄 开源许可

**MWU** 基于 **[AGPL-3.0 许可证](./LICENSE)** 开源。

## 🙏 致谢

### 📦 开源项目

- **[NaiveUI](https://github.com/tusen-ai/naive-ui)**\
  A Vue 3 Component Library. Fairly Complete. Theme Customizable. Uses TypeScript. Fast.
  
- **[FastAPI](https://github.com/fastapi/fastapi)**\
  FastAPI framework, high performance, easy to learn, fast to code, ready for production

- **[Nuitka](https://github.com/Nuitka/Nuitka)**\
  Nuitka is a Python compiler written in Python.

- **[Vite](https://github.com/vitejs/vite)**\
  Next Generation Frontend Tooling. It's fast!
  
- **[MaaFramework](https://github.com/MaaAssistantArknights/MaaFramework)**\
  基于图像识别的自动化黑盒测试框架。
  
- **[VueDraggablePlus](https://github.com/Alfred-Skyblue/vue-draggable-plus)**\
  支持 Vue2 和 Vue3 的拖拽组件
  
- **[Plyer](https://github.com/kivy/plyer)**\
  Plyer is a platform-independent Python wrapper for platform-dependent APIs
  
- **[marked](https://github.com/markedjs/marked)**\
  A markdown parser and compiler. Built for speed.
  
- **[tailwindcss](https://github.com/tailwindlabs/tailwindcss)**\
  A utility-first CSS framework for rapid UI development.

- **[Oxlint](https://oxc.rs/docs/guide/usage/linter.html)**\
  Oxlint is designed to catch erroneous or useless code without requiring any configurations by default.

### 👥 开发者

感谢所有为 **MWU** 做出贡献的开发者，以及 MAA 社区各位小伙伴提供的无私帮助与建议。

<a href="https://github.com/ravizhan/MWU/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=ravizhan/MWU&max=1000" alt="Contributors to MWU"/>
</a>