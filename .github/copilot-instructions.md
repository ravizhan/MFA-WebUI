# MWU Workspace Instructions

## Project Overview
- MWU is a frontend-backend separated project based on Vue 3 + FastAPI + MaaFramework.
- Backend entry is `main.py`, frontend source is in `front/`, frontend build output is in `page/`.
- Go updater is an independent module in `updater/`.

## Scope And Layering
- This file defines workspace-wide baseline rules.
- Backend-focused details are in `.github/instructions/backend.instructions.md`.
- Frontend-focused details are in `.github/instructions/front.instructions.md`.

## Architecture Boundaries
- Backend runtime and API: `main.py`, `maa_utils.py`, `maa_worker/`, `models/`, `services/`.
- Frontend app: `front/src/`.
- Runtime configuration: `config/`.
- Resource files: `resource/`.
- Dynamic custom agent extensions: `agent/custom/action/`, `agent/custom/reco/`, `agent/custom/sink/`.

## Build And Run
- Frontend:
  - `cd front && pnpm dev`
  - `cd front && pnpm build`
  - `cd front && pnpm lint`
  - `cd front && pnpm format`
- Backend:
  - `uv run main.py`
- Updater:
  - `cd updater && go build`
- Full packaging steps: see `README.md` and `.github/workflows/build.yml`.
- There is no dedicated repository-wide test suite entrypoint; run relevant build/lint/smoke checks for changed areas.

## Dependency Management Rules
- Python dependencies must be managed by `uv`.
  - Add/remove packages with `uv add` / `uv remove`.
  - Do not use ad-hoc `pip install` to mutate project dependencies.
  - Keep `pyproject.toml` and `uv.lock` consistent.
- Frontend dependencies (Node/TypeScript/Vue) must be managed by `pnpm` in `front/`.
  - Add/remove packages with `pnpm add` / `pnpm remove`.
  - Keep `front/pnpm-lock.yaml` consistent.
  - Require Node.js `>=24.13.0`.
- Go dependencies in `updater/` must be managed by Go Modules.
  - Use `go get` and `go mod tidy` when changing dependencies.
  - Keep `updater/go.mod` and `updater/go.sum` consistent.

## Library Usage Guardrail
- Before introducing, upgrading, or replacing any third-party library, you must query the related official documentation via Context7 tools first.
- Minimum required flow:
  1. Resolve library ID with Context7.
  2. Query docs for the exact API/version you plan to use.
  3. Implement code only after confirming usage from docs.

## Code Conventions
- All newly added or modified code comments should be in Chinese.
- Keep symbol names, framework API names, and protocol fields unchanged when they are defined externally.
- Prefer small, focused changes; avoid unrelated refactors.

## Known Pitfalls
- Do not create a top-level Python package named `utils` in this repository.
  - Dynamic agent loading can cause import resolution conflicts with `agent/utils`.
- Vite dev server proxies `/api` to `http://localhost:55666`; backend should be running during frontend local development.

## Documentation Map
- Architecture and development commands: `README.md`.
- Build matrix and CI packaging details: `.github/workflows/build.yml`.
- Commit message conventions: `.github/.copilot-commit-message-instructions.md`.
- Backend scoped rules: `.github/instructions/backend.instructions.md`.
- Frontend scoped rules: `.github/instructions/front.instructions.md`.