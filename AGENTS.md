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

Follow module boundaries; keep backend, frontend, and updater changes scoped. Python uses `uv` and snake_case. Frontend files use TypeScript/Vue conventions, 2-space indentation, LF endings, 100-column formatting, double quotes, and no semicolons per `front/.editorconfig` and `front/.oxfmtrc.json`. Do not hand-edit generated declarations.

## Testing Guidelines

There is no unified test suite. Validate the affected layer: backend changes should smoke-run with `uv run main.py`; frontend changes should pass `pnpm build` and `pnpm lint`; updater changes should pass `go build`. Add focused tests or smoke scripts for hard-to-verify behavior.

## Commit & Pull Request Guidelines

Use Conventional Commits, matching history: `feat: ...`, `fix(scope): ...`, `build: ...`, `deps: ...`, or `docs: ...`. Keep subjects short and omit trailing periods. PRs should describe the change, list validation, link issues, and include screenshots or recordings for visible frontend changes.

---

## Mandatory Workflow — Before You Write Code

These steps are **required** before any code change. Skipping them is a violation.

### 1. Read Project Memory First

Before writing code, use Engram `mem` tools to check what's already known about the part of the project you're touching:

- Call `mem_context` or `mem_search` with keywords matching your target module (e.g. `"agent loader"`, `"task pipeline"`, `"api contract"`).
- If the search returns a match, call `mem_get_observation` for the full content.
- If you're working in an area covered by an active `topic_key` (see table below), read that entry first to understand prior decisions and constraints.

This ensures you don't repeat past mistakes, undo intentional design decisions, or miss documented gotchas.

### 2. Query Third-Party Library Docs Before Use

Before writing or modifying code that uses a **third-party library** (Python package, npm package, Go module, or any external dependency):

1. Call `mcphub_context7-resolve-library-id` to get the Context7 library ID.
2. Call `mcphub_context7-query-docs` with your specific usage question.
3. For GitHub-hosted projects (e.g. `MaaXYZ/MaaFramework`), you may also use `mcphub_deepwiki-read_wiki_structure` / `mcphub_deepwiki-read_wiki_contents` as an alternative or supplement.
4. **Base your edit on current docs**, not assumptions about API behavior.

> Exception: Trivial boilerplate (e.g. `import os`, `console.log`, standard library usage) that you know with certainty does not require a docs lookup.

### 3. Understand Architecture Impact

Determine whether your change touches any of the active architecture topic keys (see the table in the Memory Persistence section below). If it does, you must update the corresponding architecture observation **after** the change.

---

## Mandatory Workflow — After You Write Code

### 4. Save Change Memory Immediately

After every code change (backend, frontend, updater, config, or infrastructure), save a structured memory entry using `mem_save`. Use the following rules:

| Change Type | `type` field | What to include |
|---|---|---|
| Routine code change | `manual` | Scope, purpose, files touched |
| Bug fix | `bugfix` | Root cause + fix approach (not just what changed, but why the bug existed) |
| Architecture/design decision | `decision` or `architecture` | The decision, rationale, and alternatives considered |
| File moved / module restructured | `architecture` | Old vs new locations + rationale |
| Configuration change | `config` | What changed and why |

### Save Format

```
**What**: [concise description of what was done]
**Why**: [the reasoning, user request, or problem that drove it]
**Where**: [files/paths affected]
**Learned**: [gotchas, edge cases, non-obvious things — omit if none]
```

### 5. Update Architecture Observations

If the change touches an area covered by an active architecture topic key (see table below), you must **update** the corresponding entry — do not create a duplicate:

- Call `mem_save` with the same `topic_key` — this **upserts** (replaces the latest entry for that key).
- In the content, explain how the architecture evolved: what changed structurally, why, and any new constraints introduced.
- If you're unsure which `topic_key` to use, call `mem_suggest_topic_key` first.

### 6. End-of-Session Summary (Mandatory)

Before the session ends, call `mem_session_summary` with the following structure:

```
## Goal
[What we worked on this session — one sentence]

## Instructions
[User preferences, constraints, or context discovered — skip if none]

## Discoveries
- [Technical findings, gotchas, non-obvious learnings]

## Accomplished
- [Completed items with key implementation details]

## Next Steps
- [What remains — for the next session]

## Relevant Files
- path/to/file — [role in the architecture or what changed]
```

---

## Architecture Topic Keys (Evolving Topics)

For long-lived architectural concerns, use a stable `topic_key` so that each update enriches a single observation instead of creating duplicates. **If your change touches any of these, you must read the corresponding entry before starting AND update it after finishing.**

| Topic Key | Scope | Key Files | Critical Gotchas |
|---|---|---|---|
| `architecture/overview` | Project-wide: tech stack, entry points, module map | main.py, app_state.py, maa_utils.py | MaaWorker is a DI container, not a service; version file is stale in dev |
| `architecture/api-contract` | Backend/frontend API boundary | main.py (routes), models/api.py, front/src/services/api/ + realtime/ | ~30 flat routes, SSE via `/api/logs`, RealtimeEventName must stay in sync across backend+frontend; frontend uses raw `fetch()`, not axios |
| `architecture/task-pipeline` | Task creation → scheduling → execution → result flow | maa_worker/task_service.py, pipeline_override.py, scheduler_manager.py, models/task_config.py | 5-layer pipeline_override merge (later wins); stop_flag polled between AND during tasks; APScheduler module-level singleton |
| `architecture/agent-loader` | Dynamic agent code loading in `maa_worker/` | maa_worker/agent_loader.py, agent_service.py | Decorator regex is fragile — ONLY double quotes match (`@AgentServer.custom_action("...")`); single quotes silently fail |
| `architecture/state-model` | Shared state (`app_state.py`) and its consumers | app_state.py, maa_worker/runtime.py, main.py (log_monitor) | Thread→asyncio bridge via `message_conn` (SimpleQueue); `configuration_locked` is a one-way ratchet; services mutate each other's state directly |
| `architecture/deployment` | Build, packaging, CI/CD | .github/workflows/build.yml, deploy/*, updater/main.go | Nuitka + Go cross-compile; Go updater uses exit code 10 for self-update; xxh3 for file diff (not cryptographic); safeJoin() path traversal defense |

### When to read architecture memory before coding

Always call `mem_search` with the relevant topic_key or keywords before touching code in any of these areas. The saved observations contain edge cases, gotchas, and design rationale that are not obvious from reading the code alone.

### When to update architecture memory after coding

If your change:
- Adds or removes a route → update `architecture/api-contract`
- Changes task flow, pipeline override, or scheduler → update `architecture/task-pipeline`
- Touches agent loading, decorator parsing, or agent lifecycle → update `architecture/agent-loader`
- Alters AppState, runtime state, or the thread→asyncio bridge → update `architecture/state-model`
- Changes build, deployment, or updater → update `architecture/deployment`
- Affects the overall architecture or module boundaries → update `architecture/overview`

## Memory Persistence (Engram) — Quick Reference

### When to Save

| Situation | Action |
|---|---|
| Before writing any code | `mem_search` / `mem_context` to read project memory |
| Using a third-party library | `mcphub_context7-resolve-library-id` + `mcphub_context7-query-docs` (or deepwiki) |
| After any code change | `mem_save` with type `manual`, `bugfix`, `decision`, or `architecture` |
| Architecture-involved change | Update the matching `architecture/*` topic_key entry |
| End of session | `mem_session_summary` |

### Format Template

```
**What**: [concise description of what was done]
**Why**: [the reasoning, user request, or problem that drove it]
**Where**: [files/paths affected]
**Learned**: [gotchas, edge cases, non-obvious things — omit if none]
```

### Guidance

- Err on the side of saving — a memory that seems obvious today may save an hour of rediscovery next month.
- When a code change touches an architecture topic key, update both the manual entry (what changed) and the relevant architecture topic (why it matters structurally).
- At the end of a session, call `mem_session_summary` to persist a comprehensive overview.
- If unsure about a topic_key, call `mem_suggest_topic_key` first.

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


<!-- headroom:rtk-instructions -->
# RTK (Rust Token Killer) - Token-Optimized Commands

When running shell commands, **always prefix with `rtk`**. This reduces context
usage by 60-90% with zero behavior change. If rtk has no filter for a command,
it passes through unchanged — so it is always safe to use.

## Key Commands
```bash
# Git (59-80% savings)
rtk git status          rtk git diff            rtk git log

# Files & Search (60-75% savings)
rtk ls <path>           rtk read <file>         rtk grep <pattern>
rtk find <pattern>      rtk diff <file>

# Test (90-99% savings) — shows failures only
rtk pytest tests/       rtk cargo test          rtk test <cmd>

# Build & Lint (80-90% savings) — shows errors only
rtk tsc                 rtk lint                rtk cargo build
rtk prettier --check    rtk mypy                rtk ruff check

# Analysis (70-90% savings)
rtk err <cmd>           rtk log <file>          rtk json <file>
rtk summary <cmd>       rtk deps                rtk env

# GitHub (26-87% savings)
rtk gh pr view <n>      rtk gh run list         rtk gh issue list

# Infrastructure (85% savings)
rtk docker ps           rtk kubectl get         rtk docker logs <c>

# Package managers (70-90% savings)
rtk pip list            rtk pnpm install        rtk npm run <script>
```

## Rules
- In command chains, prefix each segment: `rtk git add . && rtk git commit -m "msg"`
- For debugging, use raw command without rtk prefix
- `rtk proxy <cmd>` runs command without filtering but tracks usage
<!-- /headroom:rtk-instructions -->
