---
description: "Use when modifying MWU backend Python runtime, FastAPI endpoints, worker scheduling, models, or backend services. Covers dependency rules, API compatibility, and safe change boundaries."
name: "MWU Backend Guidelines"
applyTo: "main.py,maa_utils.py,app_state.py,scheduler_manager.py,json_utils.py,maa_worker/**/*.py,models/**/*.py,services/**/*.py,agent/**/*.py"
---

# MWU 后端开发指引

- 优先在后端边界内修改：`main.py`、`maa_utils.py`、`maa_worker/`、`models/`、`services/`。
- 新增或修改注释时使用中文；外部协议字段、框架 API 名称保持不变。
- 依赖管理使用 `uv`：新增依赖使用 `uv add`，删除依赖使用 `uv remove`，并保持 `pyproject.toml` 与 `uv.lock` 同步。
- 引入或升级第三方库前，先通过 Context7 完成文档确认流程：解析库 ID、查询目标版本 API、确认后再落代码。
- 避免创建顶层 Python 包 `utils`，防止与 agent 动态加载路径冲突。
- 保持改动小而聚焦，避免无关重构。
- 涉及前后端联调时，注意前端开发代理会把 `/api` 转发到 `http://127.0.0.1:55666`。
- 本地运行后端使用 `uv run main.py`，提交前至少完成相关路径的基本自检。