# Repository Guidelines

## Project Structure & Module Organization
`main.py` is the FastAPI entrypoint and serves the built frontend from `page/`. Backend domain code is split across `maa_worker/` for task runtime and device orchestration, `models/` for Pydantic models, and `services/` for business services such as updates. `updater/` contains the Go-based updater binary. Frontend code lives in `front/src/`: `app/` for bootstrapping, router, theme, and i18n; `views/` for page composition; `components/` for UI blocks; `stores/` for Pinia state; `services/` for API/SSE access; `types/` and `utils/` for shared TS models and helpers. `deploy/` holds packaging and CI scripts.

## Build, Test, and Development Commands
Use `uv` for Python, `pnpm` for the frontend, and Go tooling for the updater.

- `uv sync`: install Python dependencies from `pyproject.toml` and `uv.lock`.
- `uv run main.py`: start the FastAPI app on `http://127.0.0.1:55666`.
- `cd front && pnpm install`: install frontend dependencies.
- `cd front && pnpm dev`: run the Vite dev server with `/api` proxied to the backend.
- `cd front && pnpm build`: build the frontend into `page/`.
- `cd front && pnpm lint`: run `oxlint`.
- `cd front && pnpm format`: format frontend files with `oxfmt`.
- `cd updater && go build`: compile the updater.

## Coding Style & Naming Conventions
Python uses 4-space indentation, `snake_case` for functions/modules, and typed Pydantic models in `models/`. Keep backend changes scoped to the relevant module instead of growing `maa_utils.py`. Vue single-file components use `PascalCase` filenames such as `PanelView.vue`; TypeScript modules and stores use `camelCase` names such as `taskConfig.ts`. Follow the existing Vite/Vue style and run `pnpm format` before submitting. Avoid adding a top-level `utils` Python package; it conflicts with agent-loading conventions.

## Testing Guidelines
There is no committed first-party automated test suite yet. Every change should at minimum pass `cd front && pnpm lint`, `cd front && pnpm build`, and any relevant `go build` or `uv run main.py` smoke test. PRs that change runtime behavior should describe the manual verification performed, especially around `interface.json`, scheduling, SSE events, and updater flows.

## Commit & Pull Request Guidelines
Follow the existing Conventional Commit pattern: `feat:`, `refactor:`, `chore:`, `ci(build):`, or `BREAKING:`. Keep subjects short and imperative; scoped forms like `refactor(agent): ...` match current history. PRs should include a concise summary, linked issue if applicable, validation steps, and screenshots for frontend changes. Call out schema or config-impacting changes explicitly when touching `interface.json`, `config/`, or packaging scripts.

## Configuration Tips
Manage Python dependencies with `uv`, frontend dependencies with `pnpm`, and Go dependencies with Go modules. Keep external API fields and protocol keys stable. Review `.github/instructions/` before larger changes.