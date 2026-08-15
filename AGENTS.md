# Repository Guidelines

## Project Structure & Module Organization

MWU is a generic UI for `https://github.com/MaaXYZ/MaaFramework`. Backend entry is `main.py`; shared state in `app_state.py`; MAA orchestration in `maa_utils.py`; scheduler logic in `scheduler_manager.py`; services in `services/` and `maa_worker/`; models in `models/`. Frontend code is under `front/src/`: `app/`, `services/api/`, `stores/`, `views/`, and `components/`. Static build output is served from `page/`; deployment helpers live in `deploy/`, CI in `.github/`, and updater code in `updater/`.

## User Integration Scope

Users bring their own MaaFramework `resource/` folder, `interface.json`, and `agent/` code. Treat these as integration inputs, not MWU development targets. Improve the generic loader/runtime; do not bake in project-specific resources, tasks, or agent behavior.

## Build, Test, and Development Commands

- `uv sync`: install Python dependencies.
- `uv run main.py`: start FastAPI on `127.0.0.1:5566`.
- `cd front && pnpm dev`: run Vite with API proxying.
- `cd front && pnpm build`: build frontend output to `../page`.
- `cd front && pnpm lint`: run oxlint.
- `cd front && pnpm format`: format frontend files with oxfmt.
- `cd updater && go build`: build the Go updater.
- `pre-commit run --all-files`: run lockfile/format hooks.

## Coding Style & Naming Conventions

Follow module boundaries; keep backend, frontend, and updater changes scoped. Python uses `uv` and snake_case. Frontend files use TypeScript/Vue conventions, 2-space indentation, LF endings, 100-column formatting, double quotes, and no semicolons per `front/.editorconfig` and `front/.oxfmtrc.json`. Do not hand-edit generated declarations.

## Testing Guidelines

There is no unified test suite. Validate the affected layer: backend changes should smoke-run with `uv run main.py`; frontend changes should pass `pnpm build` and `pnpm lint`; updater changes should pass `go build`. Add focused tests or smoke scripts for hard-to-verify behavior.

## Commit & Pull Request Guidelines

Use Conventional Commits, matching history: `feat: ...`, `fix(scope): ...`, `build: ...`, `deps: ...`, or `docs: ...`. Keep subjects short and omit trailing periods. PRs should describe the change, list validation, link issues, and include screenshots or recordings for visible frontend changes.

## Working Practices (AI Assistants)

- **Third-party libraries**: before adding a new dependency or changing usage of an existing one, query the latest official documentation (context7 docs, library source, official site) — never assume API facts from memory. Version pins in this repo are locked (see Runtime/Tooling Preferences); verify any new dependency against both runtimes before introducing it.
- **Subagents**: use `task` subagents (read-only `scout` for investigation) for independent work slices — multi-file changes, refactors, research — to keep the main agent's context concise. Own the decomposition and cross-task contracts; don't delegate the top-level plan.
- **Memory**: before writing code, `recall`/`reflect` to quickly load current codebase state and conventions; after finishing work, `retain` durable facts (decisions, changes, pitfalls) so future sessions stay current.

## Agent-Specific Notes

Preserve the backend/frontend API contract and keep `interface.json` path handling rooted at the app directory. `maa_worker/agent_loader.py` contains the dynamic-loading "magic" that imports and registers code from the user's `agent/` folder. Its custom decorator parsing is string-pattern based and can silently fail if expected decorator forms change.

### Key Architecture Constraints (Non-Obvious)

These are hard-won learnings from previous sessions — do not reintroduce these issues:

- **MaaWorker is a DI container**, not a service. It creates Resource singleton + Tasker + runtime state dataclasses, instantiates 6 services each getting a back-ref to `self`. Services mutate shared state via `self.worker.*_state` directly — no inter-service direct calls.
- **Thread→asyncio bridge**: Worker runs MAA on threads, pushes `RealtimeEvent` to `app_state.message_conn` (`queue.SimpleQueue`). The `log_monitor` asyncio task polls every 100ms → normalizes → appends to `history_message` deque (maxlen 2000) → `LogBroadcaster` fan-out to SSE clients. **If log_monitor dies, SSE goes silent.**
- **`configuration_locked` is a one-way ratchet**: Once device + resource are set, `connect()` / `set_resource()` refuse. Only `reset_connection_state()` (called on connection failure) releases it.
- **`stop_flag` is polled both between tasks AND during each task**: Inside `run_process()`, the inner `while not t.done: sleep(0.5); if stop_flag: tasker.post_stop().wait(); return` loop is how mid-pipeline abort works.
- **Decorator regex is fragile**: Only `@AgentServer.custom_action("...")` with **double quotes** matches. Single quotes → silent failure. Class def must be on the line immediately after the decorator.
- **Frontend uses raw `fetch()`**, not axios. No shared interceptors. Every API module inlines `res.json()` + `status === "success"` check + `showGlobalMessage()` on error.
- **`version` file is stale in dev** (says `v0.11.0` vs `pyproject.toml` `0.15.1`). CI rewrites it with `github.ref_name`. `agent_service.build_pi_env()` reads it directly — mismatch is expected in dev.
