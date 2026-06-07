# Repository Guidelines

## Project Structure & Module Organization

MWU is a generic UI for `https://github.com/MaaXYZ/MaaFramework`. Backend entry is `main.py`; shared state in `app_state.py`; MAA orchestration in `maa_utils.py`; scheduler logic in `scheduler_manager.py`; services in `services/` and `maa_worker/`; models in `models/`. Frontend code is under `front/src/`: `app/`, `services/api/`, `stores/`, `views/`, and `components/`. Static build output is served from `page/`; deployment helpers live in `deploy/`, CI in `.github/`, and updater code in `updater/`.

## User Integration Scope

Users bring their own MaaFramework `resource/` folder, `interface.json`, and `agent/` code. Treat these as integration inputs, not MWU development targets. Improve the generic loader/runtime; do not bake in project-specific resources, tasks, or agent behavior.

## Build, Test, and Development Commands

- `uv sync`: install Python dependencies.
- `uv run main.py`: start FastAPI on `127.0.0.1:55666`.
- `cd front && pnpm dev`: run Vite with API proxying.
- `cd front && pnpm build`: build frontend output to `../page`.
- `cd front && pnpm lint`: run oxlint.
- `cd front && pnpm format`: format frontend files with oxfmt.
- `cd updater && go build`: build the Go updater.
- `pre-commit run --all-files`: run lockfile/format hooks.

## Coding Style & Naming Conventions

Follow module boundaries; keep backend, frontend, and updater changes scoped. Python uses `uv` and snake_case. Frontend files use TypeScript/Vue conventions, 2-space indentation, LF endings, 100-column formatting, double quotes, and no semicolons per `front/.editorconfig` and `front/.oxfmtrc.json`. Do not hand-edit generated declarations. Before changing code that uses a third-party library, query current docs with the Context7 tool and base the edit on those docs.

## Testing Guidelines

There is no unified test suite. Validate the affected layer: backend changes should smoke-run with `uv run main.py`; frontend changes should pass `pnpm build` and `pnpm lint`; updater changes should pass `go build`. Add focused tests or smoke scripts for hard-to-verify behavior.

## Commit & Pull Request Guidelines

Use Conventional Commits, matching history: `feat: ...`, `fix(scope): ...`, `build: ...`, `deps: ...`, or `docs: ...`. Keep subjects short and omit trailing periods. PRs should describe the change, list validation, link issues, and include screenshots or recordings for visible frontend changes.

## Agent-Specific Notes

Preserve the backend/frontend API contract and keep `interface.json` path handling rooted at the app directory. `maa_worker/agent_loader.py` contains the dynamic-loading "magic" that imports and registers code from the user's `agent/` folder. Its custom decorator parsing is string-pattern based and can silently fail if expected decorator forms change.
