<!-- markdownlint-disable MD033 MD041 -->

<p align="center">
  <img alt="LOGO" src="https://github.com/ravizhan/MFA-WebUI/blob/main/logo.jpg" width="256" height="256" />
</p>

<div align="center">

# MFA-WebUI

<!-- prettier-ignore-start -->
<!-- markdownlint-disable-next-line MD036 -->
_✨ 基于 **[Vue](https://github.com/vuejs/vue)** 和 **[FastAPI](https://github.com/fastapi/fastapi)**  的 **[MAAFramework](https://github.com/MaaXYZ/MaaFramework)** 通用 WebUI 项目 ✨_

**本项目尚未Production-Ready，欢迎测试并提供反馈**
<!-- prettier-ignore-end -->

  <img alt="license" src="https://img.shields.io/github/license/ravizhan/MFA-WebUI">
  <img alt="Python" src="https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fravizhan%2FMFA-WebUI%2Frefs%2Fheads%2Fmain%2Fpyproject.toml">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blueviolet">
  <img alt="commit" src="https://img.shields.io/github/commit-activity/m/ravizhan/MFA-WebUI">
  <img alt="stars" src="https://img.shields.io/github/stars/ravizhan/MFA-WebUI?style=social">
</div>

## ✨ 项目特点

- 🚀 **现代化技术栈** - 前后端分离架构，Vue 3 + FastAPI
- 🎨 **美观易用** - 基于 NaiveUI 组件库，界面简洁美观，支持深色模式自动切换
- 🔌 **魔改 Agent 实现** - 通过动态解析导入，无需额外 Python 环境
- 🔧 **高度可定制** - Python 代码简洁易修改，轻松实现各种定制需求
- 🔔 **系统通知** - 依托 Plyer 和浏览器API实现跨平台双渠道系统通知
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

使用 [MaaFramework 项目模板](https://github.com/MaaXYZ/MaaPracticeBoilerplate) 创建项目后，只需将 `.github/workflows/install.yml` 替换为本项目的 [deploy/install.yaml](https://github.com/ravizhan/MFA-WebUI/blob/main/deploy/install.yml) 即可

### ⚙️ 配置清单

| 配置         | 默认值                  | 修改方法                                                     |
| ------------ | ----------------------- | ------------------------------------------------------------ |
| 压缩包名     | 仓库名-版本号-平台-架构 | [deploy/install.yml#L170](https://github.com/ravizhan/MFA-WebUI/blob/baeec32ecc5db8ea6390ceb5575d73e2d2754ba6/deploy/install.yml#L170)，注意下方各处也要一并修改 |
| 可执行文件名 | MFA-WebUI               | 暂不可修改                                                   |
| LOGO         |                         | 暂不可修改                                                   |

## 🏗️ 项目架构与开发

> **如果您需要更多的定制化功能或想为本项目做出贡献，请阅读以下部分**

### 📐 架构概览

项目采用前后端分离架构：

- **后端**：FastAPI (Python 3.12+)，提供 RESTful API 和 WebSocket 服务，运行在 `http://127.0.0.1:55666`
- **前端**：Vue 3 + NaiveUI + Vite + UnoCSS + Pinia，构建输出到 `page/` 目录
- **核心交互**：通过 WebSocket 实现任务状态和日志的实时推送

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

#### 📁 项目文件目录

```
MFA-WebUI/
├── main.py                      # FastAPI 应用入口，自动打开浏览器
├── maa_utils.py                 # MaaWorker 类，处理所有 MAA 框架交互
│
├── config/                      # 配置文件目录
│   ├── settings.json            # 应用设置
│   └── maa_option.json          # MAA 选项配置
│
├── models/                      # 数据模型目录
│   ├── api.py                   # API 请求/响应模型
│   ├── interfaceV1.py           # interfaceV1 数据模型
│   ├── interfaceV2.py           # interfaceV2 数据模型
│   └── settings.py              # 设置数据模型
│
└── front/                       # 前端项目目录
    └── src/                     # 源代码目录
        ├── App.vue              # 根组件
        ├── main.ts              # 前端入口文件
        ├── components/          # Vue 组件
        │   ├── LeftPanel.vue    # 左侧面板组件
        │   ├── MediumPanel.vue  # 中间面板组件
        │   ├── OptionItem.vue   # 选项项组件
        │   └── RightPanel.vue   # 右侧面板组件
        ├── router/              # Vue Router 路由配置
        │   └── index.ts
        ├── script/              # API 和 WebSocket 工具函数
        │   ├── api.ts
        │   └── ws.ts
        ├── stores/              # Pinia 状态管理
        │   ├── index.ts         # Store 入口
        │   ├── interface.ts     # 接口状态管理
        │   ├── settings.ts      # 设置状态管理
        │   └── userConfig.ts    # 用户配置状态管理
        ├── types/               # TypeScript 类型定义
        │   ├── interfaceV1.ts   # interfaceV1 类型
        │   ├── interfaceV2.ts   # interfaceV2 类型
        │   └── settings.ts      # 设置类型
        └── views/               # 页面视图组件
            ├── PanelView.vue    # 主面板视图
            └── SettingView.vue  # 设置视图
```

## 📄 开源许可

**MFA-WebUI** 基于 **[AGPL-3.0 许可证](./LICENSE)** 开源。

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

感谢所有为 **MFA-WebUI** 做出贡献的开发者，以及 MAA 社区各位小伙伴提供的无私帮助与建议。

<a href="https://github.com/ravizhan/MFA-WebUI/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=ravizhan/MFA-WebUI&max=1000" alt="Contributors to MFA-WebUI"/>
</a>