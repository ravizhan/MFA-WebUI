---
description: "Use when editing MWU frontend Vue/TypeScript files in front/, including components, views, stores, services, i18n, and Vite/Uno config updates."
applyTo: "front/src/**/*.{vue,ts,tsx,js,jsx},front/{vite.config.ts,uno.config.ts,tsconfig.json,package.json}"
---

# MWU Frontend Instructions

## Scope
- This file applies to frontend work under `front/`.
- Keep global project constraints from `.github/copilot-instructions.md`.

## Project Structure
- Page-level components belong in `front/src/views/`.
- Reusable UI components belong in `front/src/components/` and use PascalCase filenames.
- State logic belongs in `front/src/stores/` and uses `useXxxStore` naming.
- API and realtime interaction code belongs in `front/src/services/`.
- Shared types belong in `front/src/types/`.
- i18n files belong in `front/src/locales/`.

## Frontend Conventions
- Prefer relative imports used by current codebase style; do not introduce path alias conventions unless explicitly requested.
- Use TypeScript-first patterns and keep type definitions close to domain modules.
- New or updated comments should be in Chinese.
- Keep external protocol fields and API contract keys unchanged.

## UI And Style
- Keep UI based on Naive UI + UnoCSS patterns already used in `front/src/`.
- Prefer existing composition patterns over introducing new state/UI frameworks.
- Avoid broad visual refactors when implementing feature or bug-fix tasks.

## I18n And User-Facing Text
- New user-facing strings must be i18n-friendly.
- Update locale resources in `front/src/locales/` consistently when adding text.

## Networking And Runtime Assumptions
- During local development, frontend `/api` requests are proxied by Vite to `http://127.0.0.1:55666`.
- Keep frontend-backend integration compatible with existing backend API behavior.

## Dependencies And Tooling
- Manage frontend dependencies only with `pnpm` inside `front/`.
- Before introducing, upgrading, or replacing third-party frontend libraries, query official docs with Context7 first.
- Keep `front/pnpm-lock.yaml` in sync with dependency changes.

## Validation Commands
- `cd front && pnpm dev`
- `cd front && pnpm build`
- `cd front && pnpm lint`
- `cd front && pnpm format`

## References
- Architecture and development workflow: `README.md`
- Workspace-wide coding guardrails: `.github/copilot-instructions.md`