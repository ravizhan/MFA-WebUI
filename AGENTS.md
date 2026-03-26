# Repository Guidelines

## Project Structure & Module Organization
`main.py` is the FastAPI entrypoint; backend code lives in `maa_utils.py`, `app_state.py`, `scheduler_manager.py`, `maa_worker/`, `models/`, and `services/`. Runtime config lives in `config/`, resources in `resource/`, the Vue app in `front/`, and the built frontend in `page/`. The Go updater is isolated in `updater/`, and dynamic extensions belong under `agent/custom/`.

## Build, Test, and Development Commands
Use the repo toolchains directly:

- `uv sync`: install and lock Python dependencies from `pyproject.toml` and `uv.lock`.
- `uv run main.py`: start the backend at `http://127.0.0.1:55666`.
- `cd front && pnpm install`: install frontend dependencies.
- `cd front && pnpm dev`: run the Vite dev server with `/api` proxied to the backend.
- `cd front && pnpm build`: build the frontend into `page/`.
- `cd front && pnpm lint && pnpm format`: apply frontend linting and formatting.
- `cd updater && go build`: compile the updater.
- `uv run pre-commit run -a`: run the repo formatting hooks before review.

## Coding Style & Naming Conventions
Python targets 3.12+ and uses 4-space indentation. Vue/TypeScript files in `front/` use the existing 2-space style and relative imports. Keep comments in Chinese when adding or updating them. Use PascalCase for Vue components, `useXxxStore` for Pinia stores, and keep shared types in `front/src/types/`. Do not create a top-level Python package named `utils`; it conflicts with dynamic agent loading.

## Testing Guidelines
There is no single repository-wide test command yet. Validate the area you changed: backend changes should at least boot with `uv run main.py`, frontend changes should pass `pnpm build` and `pnpm lint`, and updater changes should pass `go build`. If you add tests, use native names such as `test_*.py` or `*.spec.ts` and document the command in your PR.

## Commit & Pull Request Guidelines
Commits follow Conventional Commits, usually with concise Chinese subjects, for example `fix(api): 修复任务状态推送` or `refactor(front): 调整设置页结构`. Keep commits focused and use scopes when helpful. PRs should include a short summary, linked issue or context, the validation commands you ran, and screenshots for visible UI changes. Call out dependency updates explicitly and keep lockfiles in sync.

## Security & Configuration Tips
Manage Python dependencies with `uv`, frontend dependencies with `pnpm`, and Go dependencies with Go modules. Keep external API fields and protocol keys stable. Review `.github/instructions/` before larger changes.
