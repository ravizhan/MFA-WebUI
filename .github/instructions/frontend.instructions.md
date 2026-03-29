---
description: "Use when editing MWU frontend Vue/TypeScript code in front/, including views, components, stores, api clients, and Vite/Uno configs. Covers state-api consistency, scan_select behavior, task ordering persistence, and frontend validation."
name: "MWU Frontend Guidelines"
applyTo: "front/src/**/*.{vue,ts,tsx,js,jsx},front/{vite.config.ts,uno.config.ts,package.json,.oxlintrc.json}"
---

# MWU Frontend Instructions

## Scope
- Applies to frontend code under `front/`.
- Keep workspace-wide defaults from `.github/copilot-instructions.md` as baseline.

## Structure And Boundaries
- Keep application bootstrap concerns under `front/src/app/`.
- Keep API calls inside `front/src/services/api/` modules and re-export via `front/src/services/api/index.ts`.
- Keep Pinia state logic inside `front/src/stores/`; preserve existing store boundaries (`interface`, `task-config`, `settings`, `scheduler`, `panel`).

## Contract And State Consistency
- Treat backend API envelopes as stable contracts; when backend fields change, update corresponding frontend API modules and stores in the same task.
- Preserve `scan_select` frontend behavior:
  - `useInterfaceStore.rescanScanSelectOption` should only act on `scan_select` options.
  - Rescan results should update option `cases` without breaking existing option traversal logic.
- Preserve task list persistence merge behavior in `front/src/stores/task-config/taskConfig.ts`:
  - Saved `taskOrder` should be applied when possible.
  - New tasks from interface must still be appended rather than dropped.

## Tooling And Validation
- Manage frontend dependencies only with `pnpm` in `front/`; keep `front/pnpm-lock.yaml` in sync.
- Respect runtime/build assumptions:
  - Vite build output remains `../page`.
  - Dev server `/api` proxy remains aligned with backend address configured in `vite.config.ts`.
- For frontend-only changes, run targeted validation:
  - `cd front && pnpm build`
  - `cd front && pnpm lint`

## References
- Frontend architecture and workflow: `README.md`
- Frontend build/proxy config: `front/vite.config.ts`
- Workspace-wide defaults: `.github/copilot-instructions.md`