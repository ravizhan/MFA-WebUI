"""
WakeupCoordinator (SystemTaskService): APS-owned tasks + OS native wakeup adapter.

- asyncio.Lock serializes native mutations
- on-disk state is operational-only (no desired schedule mirrors)
- APS is source of truth for name/trigger/scope; SystemSchedulerBackend is the
  WakeupAdapter (platform native register/verify/query)
- Standalone /system-register mutation API removed; use create/update/delete
  synced + reconcile/repair
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional, cast

import json_utils as json

from models.scheduler import (
    ObservedNativeState,
    OperationalState,
    ReconcileTaskResult,
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
    SystemCapabilitiesResponse,
    SystemTaskOperationalRecord,
    SystemTaskRegistration,
    SystemTaskScope,
    SystemTaskSpec,
    SystemTaskStatusResponse,
    TaskUpdateSyncedResult,
    OPERATIONAL_STATE_KEYS,
)
from scheduler_job_codec import SchedulerJobDecodeError
from scheduler_manager import SchedulerManager
from services.system_scheduler_backend import (
    SystemSchedulerBackend,
    build_capabilities,
    build_native_command,
    get_backend,
    is_capability_enabled,
    map_trigger_to_os_spec,
    validate_trigger_for_platform,
)

logger = logging.getLogger(__name__)

OPERATIONAL_STATE_VERSION = 3
LEGACY_STATE_VERSION = 2


class _SystemTaskState:
    def __init__(self, version: int = OPERATIONAL_STATE_VERSION):
        self.version = version
        self.records: list[SystemTaskOperationalRecord] = []
        self.corrupt: bool = False
        self.corrupt_backup: Optional[Path] = None
        # True when loaded from legacy state until import_scopes_into_aps completes.
        self.pending_operational_flush: bool = False


class SystemTaskService:
    """WakeupCoordinator: reconcile APS system_scope with native OS wakeups."""

    def __init__(self, app_root_dir: Path):
        self._app_root_dir = Path(app_root_dir)
        self._config_dir = self._app_root_dir / "config"
        self._state_file = self._config_dir / "system_tasks.json"
        self._backend: Optional[SystemSchedulerBackend] = None
        self._async_lock = asyncio.Lock()
        self._memory_state: Optional[_SystemTaskState] = None

    @property
    def backend(self) -> SystemSchedulerBackend:
        if self._backend is None:
            self._backend = get_backend()
        return self._backend

    @property
    def current_exe_path(self) -> str:
        exe, _ = build_native_command(
            self._app_root_dir, "00000000-0000-0000-0000-000000000000"
        )
        return exe

    def build_command_for_task(self, task_id: str) -> tuple[str, list[str]]:
        return build_native_command(self._app_root_dir, task_id)

    def get_capabilities(self) -> SystemCapabilitiesResponse:
        return build_capabilities(
            self.backend.platform_name, app_root=self._app_root_dir
        )

    # ------------------------------------------------------------------
    # persistence (operational state)
    # ------------------------------------------------------------------

    def _load_state(self) -> _SystemTaskState:
        if self._memory_state is not None and self._memory_state.pending_operational_flush:
            return self._memory_state
        if not self._state_file.exists():
            st = _SystemTaskState(version=OPERATIONAL_STATE_VERSION)
            self._memory_state = st
            return st
        try:
            with self._state_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("state root must be object")
            file_ver = int(data.get("version", LEGACY_STATE_VERSION))
            state = _SystemTaskState(version=file_ver)
            raw_regs = data.get("registrations", [])
            if not isinstance(raw_regs, list):
                raise ValueError("registrations must be list")
            for reg_data in raw_regs:
                if not isinstance(reg_data, dict):
                    raise ValueError("registration must be object")
                if file_ver <= LEGACY_STATE_VERSION:
                    state.records.append(self._migrate_legacy_reg_to_operational(reg_data))
                else:
                    state.records.append(
                        SystemTaskOperationalRecord.model_validate(
                            {k: reg_data[k] for k in OPERATIONAL_STATE_KEYS if k in reg_data}
                            | {"task_id": reg_data["task_id"]}
                        )
                    )
            if file_ver <= LEGACY_STATE_VERSION:
                # In-memory only until import_scopes_into_aps allows first operational save.
                state.pending_operational_flush = True
                state.version = LEGACY_STATE_VERSION
            else:
                state.version = OPERATIONAL_STATE_VERSION
            self._memory_state = state
            return state
        except Exception as e:
            logger.error(
                "加载 system_tasks.json 失败（保留损坏文件，fail closed）: %s", e
            )
            state = _SystemTaskState()
            state.corrupt = True
            backup = self._state_file.with_suffix(".json.corrupt")
            try:
                if not backup.exists():
                    shutil.copy2(self._state_file, backup)
                state.corrupt_backup = backup
            except Exception:
                pass
            self._memory_state = state
            return state

    def _migrate_legacy_reg_to_operational(self, data: dict) -> SystemTaskOperationalRecord:
        """In-memory legacy → operational record (never writes dummy schedules)."""
        scope_raw = data.get("desired_scope") or data.get("scope")
        last_known: Optional[SystemTaskScope] = None
        if scope_raw in ("user", "system"):
            last_known = SystemTaskScope(scope_raw)

        cleanup: list[SystemTaskScope] = []
        seen: set[SystemTaskScope] = set()

        def _add(sc: Optional[SystemTaskScope]) -> None:
            if sc is not None and sc not in seen:
                seen.add(sc)
                cleanup.append(sc)

        _add(last_known)
        mig = data.get("migration_from_scope")
        if mig in ("user", "system"):
            _add(SystemTaskScope(mig))
        for obs in data.get("observed") or []:
            if isinstance(obs, dict) and obs.get("scope") in ("user", "system"):
                _add(SystemTaskScope(obs["scope"]))
        # Lossless: keep both scopes if any ambiguity from pending/orphan.
        raw_state = data.get("state") or (
            "orphaned" if data.get("orphaned") else "active"
        )
        if raw_state in (
            "pending_register",
            "pending_cleanup",
            "orphaned",
        ) or data.get("orphaned"):
            for sc in (SystemTaskScope.USER, SystemTaskScope.SYSTEM):
                _add(sc)

        op_state: OperationalState = "active"
        last_error = data.get("last_error")
        if raw_state in ("pending_register", "pending_cleanup", "orphaned", "error"):
            op_state = "error"
            if raw_state != "error" or not last_error:
                last_error = (
                    f"migrated from legacy state={raw_state}; "
                    "normalized to error pending reconcile"
                )
        elif data.get("pending_operation") not in (None, "none"):
            op_state = "error"
            last_error = last_error or (
                f"migrated from legacy pending_operation="
                f"{data.get('pending_operation')}"
            )

        observed: list[ObservedNativeState] = []
        raw_observed = data.get("observed") or []
        if raw_observed is not None and not isinstance(raw_observed, list):
            raise ValueError(
                f"legacy registration {data.get('task_id')}: observed must be a list"
            )
        for i, obs in enumerate(raw_observed):
            if not isinstance(obs, dict):
                raise ValueError(
                    f"legacy registration {data.get('task_id')}: "
                    f"observed[{i}] is not an object"
                )
            try:
                observed.append(ObservedNativeState.model_validate(obs))
            except Exception as e:
                # Fail closed: do not drop observed entries silently.
                raise ValueError(
                    f"legacy registration {data.get('task_id')}: "
                    f"malformed observed[{i}]: {e}"
                ) from e

        platform = data.get("platform") or self.backend.platform_name
        if platform not in ("windows", "macos", "linux"):
            platform = "linux"

        return SystemTaskOperationalRecord(
            task_id=str(data["task_id"]),
            platform=cast(Literal["windows", "macos", "linux"], platform),
            state=op_state,
            last_known_scope=last_known,
            cleanup_scopes=cleanup,
            system_task_identifier=str(data.get("system_task_identifier") or ""),
            registered_exe_path=str(
                data.get("registered_exe_path") or data.get("desired_exe_path") or ""
            ),
            last_registered_at=data.get("last_registered_at"),
            last_error=last_error,
            observed=observed,
            warnings=list(data.get("warnings") or []),
        )

    def _save_state(self, state: _SystemTaskState) -> None:
        if state.corrupt:
            raise RuntimeError(
                "system_tasks.json is corrupt; refusing to overwrite. "
                f"Backup: {state.corrupt_backup}"
            )
        self._memory_state = state
        if state.pending_operational_flush:
            # Defer first operational disk write until scope import has consumed legacy.
            logger.debug("deferring operational save until scope import completes")
            return
        self._config_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "version": OPERATIONAL_STATE_VERSION,
            "registrations": [rec.to_operational_dict() for rec in state.records],
        }
        # Guard: never persist forbidden desired keys.
        for reg in data["registrations"]:
            forbidden = set(reg.keys()) - OPERATIONAL_STATE_KEYS
            if forbidden:
                raise RuntimeError(f"operational save contains forbidden keys: {forbidden}")
        tmp = self._state_file.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._state_file)
        try:
            dir_fd = os.open(str(self._config_dir), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (OSError, AttributeError):
            pass
        state.version = OPERATIONAL_STATE_VERSION

    def _find_record(
        self, state: _SystemTaskState, task_id: str
    ) -> Optional[SystemTaskOperationalRecord]:
        for rec in state.records:
            if rec.task_id == task_id:
                return rec
        return None

    # Back-compat name used by tests
    def _find_registration(
        self, state: _SystemTaskState, task_id: str
    ) -> Optional[SystemTaskOperationalRecord]:
        return self._find_record(state, task_id)

    def _build_identifier(self, task_id: str, scope: SystemTaskScope) -> str:
        return self.backend.build_identifier(task_id, scope)

    def _union_cleanup_scopes(
        self,
        rec: Optional[SystemTaskOperationalRecord],
        *extra: Optional[SystemTaskScope],
    ) -> list[SystemTaskScope]:
        seen: set[SystemTaskScope] = set()
        out: list[SystemTaskScope] = []

        def add(sc: Optional[SystemTaskScope]) -> None:
            if sc is not None and sc not in seen:
                seen.add(sc)
                out.append(sc)

        if rec is not None:
            add(rec.last_known_scope)
            for sc in rec.cleanup_scopes:
                add(sc)
            for obs in rec.observed:
                add(obs.scope)
        for sc in extra:
            add(sc)
        return out

    def _resolve_aps_scope(
        self,
        rec: SystemTaskOperationalRecord,
        task: Optional[ScheduledTask],
        *,
        aps_missing: bool = False,
    ) -> tuple[Optional[SystemTaskScope], str]:
        """Resolve status scope under APS authority.

        Returns (scope_for_status, reason_hint).
        - APS task present + system_scope user/system → that scope
        - APS task present + system_scope None → authoritative disabled (None)
        - APS task absent → diagnostic last_known_scope only (with reason)
        """
        if task is not None:
            if task.system_scope in ("user", "system"):
                return SystemTaskScope(task.system_scope), ""
            # Explicit None or invalid: do not fall back to last_known for status.
            return None, "APS system_scope is None (disabled)"
        if aps_missing:
            return rec.last_known_scope, "APS job missing"
        return rec.last_known_scope, "APS schedule unknown"

    def _hydrate_registration(
        self,
        rec: SystemTaskOperationalRecord,
        *,
        task: Optional[ScheduledTask] = None,
        aps_missing: bool = False,
        aps_error: Optional[str] = None,
        registered: Optional[bool] = None,
        verified: Optional[bool] = None,
        path_valid: Optional[bool] = None,
        reason: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> SystemTaskRegistration:
        """API DTO from operational record + optional APS task."""
        scope, scope_reason = self._resolve_aps_scope(
            rec, task, aps_missing=aps_missing
        )
        trigger = None
        name = ""
        exe = ""
        args: list[str] = []
        if task is not None and task.system_scope in ("user", "system"):
            name = task.name
            try:
                trigger = map_trigger_to_os_spec(task.trigger_config)
            except Exception:
                trigger = None
            exe, args = self.build_command_for_task(task.id)
            if path_valid is None:
                # Empty diagnostic path never counts as valid.
                path_valid = bool(
                    rec.registered_exe_path
                    and rec.registered_exe_path == exe
                    and registered is True
                    and verified is True
                )
        elif path_valid is None:
            # APS absent/disabled: path not authoritatively valid.
            path_valid = False

        if reason is None:
            if aps_error:
                reason = aps_error
            elif aps_missing:
                reason = "APS job missing"
            elif task is not None and task.system_scope is None:
                reason = "APS system_scope is None (disabled)"
            elif task is None:
                reason = "APS schedule unknown"
            else:
                reason = scope_reason or ""

        if registered is None:
            registered = False
        if verified is None:
            verified = False

        return SystemTaskRegistration(
            task_id=rec.task_id,
            task_name=name,
            platform=rec.platform,
            desired_scope=scope,
            desired_trigger=trigger,
            desired_exe_path=exe,
            desired_cli_args=list(args),
            desired_working_dir=(
                str(self._app_root_dir)
                if task is not None and task.system_scope in ("user", "system")
                else ""
            ),
            state=cast(
                Literal[
                    "pending_register",
                    "active",
                    "orphaned",
                    "pending_cleanup",
                    "error",
                ],
                rec.state,
            ),
            pending_operation="none",
            observed=list(rec.observed),
            system_task_identifier=rec.system_task_identifier,
            registered_exe_path=rec.registered_exe_path,
            last_registered_at=rec.last_registered_at,
            last_error=rec.last_error,
            warnings=list(rec.warnings),
            orphaned=False,
            scope=scope,
            trigger_spec=trigger,
            last_known_scope=rec.last_known_scope,
            cleanup_scopes=list(rec.cleanup_scopes),
            registered=registered,
            verified=verified,
            path_valid=path_valid,
            reason=reason,
            enabled=enabled,
        )

    def _status_from_record(
        self,
        rec: Optional[SystemTaskOperationalRecord],
        task_id: str,
        *,
        task: Optional[ScheduledTask] = None,
        aps_missing: bool = False,
        path_valid: Optional[bool] = None,
        os_registered: Optional[bool] = None,
        verified: Optional[bool] = None,
        reason: Optional[str] = None,
    ) -> SystemTaskStatusResponse:
        if rec is None:
            return SystemTaskStatusResponse(
                task_id=task_id,
                registered=False,
                path_valid=False,
                state=None,
                pending_operation=None,
                orphaned=False,
                reason=reason or "no operational record",
                verified=False,
            )
        registered = bool(os_registered) if os_registered is not None else False
        scope, scope_reason = self._resolve_aps_scope(
            rec, task, aps_missing=aps_missing
        )

        enabled: Optional[bool] = None
        cap_reason = ""
        cap_warnings: list[str] = []
        # Capability only when APS provides an active user/system scope.
        if task is not None and task.system_scope in ("user", "system"):
            caps = self.get_capabilities()
            enabled, cap_reason, cap_warnings = is_capability_enabled(
                caps, SystemTaskScope(task.system_scope), task.trigger_type
            )
        warnings = list(rec.warnings) + list(cap_warnings)

        if verified is None:
            verified = False
        if path_valid is None:
            if (
                task is not None
                and task.system_scope in ("user", "system")
                and registered
                and verified
                and rec.registered_exe_path
            ):
                exe, _ = self.build_command_for_task(task_id)
                path_valid = rec.registered_exe_path == exe
            else:
                # Empty/unknown diagnostic path, absent/unknown native, or no APS.
                path_valid = False

        out_reason = reason or scope_reason or ""
        if enabled is False and cap_reason:
            out_reason = out_reason or cap_reason

        return SystemTaskStatusResponse(
            task_id=task_id,
            registered=registered,
            scope=scope,
            platform=rec.platform,
            next_run_time=(
                getattr(task, "next_run_time", None)
                if task is not None and task.system_scope in ("user", "system")
                else None
            ),
            last_error=rec.last_error,
            path_valid=bool(path_valid),
            state=cast(
                Literal[
                    "pending_register",
                    "active",
                    "orphaned",
                    "pending_cleanup",
                    "error",
                ],
                rec.state,
            ),
            pending_operation="none",
            orphaned=False,
            desired_scope=scope,
            observed=list(rec.observed),
            warnings=warnings,
            enabled=enabled,
            verified=verified,
            reason=out_reason,
        )

    # ------------------------------------------------------------------
    # tri-state native query
    # ------------------------------------------------------------------

    async def _query_presence(
        self, task_id: str, scope: SystemTaskScope
    ) -> Literal["present", "absent", "unknown"]:
        try:
            present = await self.backend.is_registered(task_id, scope)
        except Exception as e:
            logger.warning(
                "native presence query unknown for %s/%s: %s",
                task_id,
                scope.value,
                e,
            )
            return "unknown"
        return "present" if present else "absent"

    async def _observe_scopes(
        self, task_id: str, scopes: list[SystemTaskScope], *, detail: str
    ) -> list[ObservedNativeState]:
        observed: list[ObservedNativeState] = []
        for sc in scopes:
            presence = await self._query_presence(task_id, sc)
            if presence == "unknown":
                present = False
                d = f"{detail}; native query error (unknown)"
            elif presence == "present":
                present = True
                d = detail
            else:
                present = False
                d = detail
            observed.append(
                ObservedNativeState(
                    scope=sc,
                    identifier=self._build_identifier(task_id, sc),
                    present=present,
                    verified=False,
                    details=d,
                )
            )
        return observed

    def _compute_registration_warnings(
        self, scope: SystemTaskScope, trigger_spec
    ) -> list[str]:
        warnings = list(
            validate_trigger_for_platform(self.backend.platform_name, trigger_spec)
        )
        caps = self.get_capabilities()
        _, _, cap_warnings = is_capability_enabled(
            caps, scope, trigger_spec.trigger_type
        )
        return warnings + list(cap_warnings)

    async def _ensure_scope_absent(
        self, task_id: str, scope: SystemTaskScope
    ) -> tuple[bool, Optional[str]]:
        presence = await self._query_presence(task_id, scope)
        if presence == "absent":
            return True, None
        if presence == "unknown":
            return False, f"native query unknown for {scope.value}"
        try:
            await self.backend.unregister(task_id, scope)
        except Exception as e:
            return False, f"unregister {scope.value} failed: {e}"
        after = await self._query_presence(task_id, scope)
        if after == "absent":
            return True, None
        if after == "unknown":
            return False, f"absence query unknown after unregister {scope.value}"
        return False, f"still present after unregister {scope.value}"

    def _tracked_scopes_for_reg(
        self,
        rec: Optional[SystemTaskOperationalRecord],
        *,
        prior_scope: Optional[SystemTaskScope] = None,
    ) -> list[SystemTaskScope]:
        scopes = self._union_cleanup_scopes(rec, prior_scope)
        if not scopes:
            return [SystemTaskScope.USER, SystemTaskScope.SYSTEM]
        return scopes

    def _persist_reg_error(self, task_id: str, message: str) -> None:
        state = self._load_state()
        r = self._find_record(state, task_id)
        if r is None:
            return
        r.state = "error"
        r.last_error = message
        self._save_state(state)

    def _upsert_error_record(
        self,
        task_id: str,
        message: str,
        *,
        scope: Optional[SystemTaskScope] = None,
        task_name: str = "",
    ) -> None:
        """Create/update operational error record without fabricated schedules."""
        del task_name  # not persisted
        state = self._load_state()
        if state.corrupt:
            return
        r = self._find_record(state, task_id)
        if r is None:
            cleanup = []
            if scope is not None:
                cleanup = [scope]
            else:
                cleanup = [SystemTaskScope.USER, SystemTaskScope.SYSTEM]
            r = SystemTaskOperationalRecord(
                task_id=task_id,
                platform=cast(
                    Literal["windows", "macos", "linux"],
                    self.backend.platform_name,
                ),
                state="error",
                last_known_scope=scope,
                cleanup_scopes=cleanup,
                last_error=message,
            )
            state.records.append(r)
        else:
            r.state = "error"
            r.last_error = message
            if scope is not None:
                r.cleanup_scopes = self._union_cleanup_scopes(r, scope)
        self._save_state(state)

    def _restore_reg_as_repair_after_aps_fail(
        self, prior: SystemTaskOperationalRecord, last_error: str
    ) -> None:
        state = self._load_state()
        if state.corrupt:
            return
        reg = prior.model_copy(deep=True)
        reg.state = "error"
        reg.last_error = last_error
        existing = self._find_record(state, reg.task_id)
        if existing is not None:
            state.records.remove(existing)
        state.records.append(reg)
        self._save_state(state)

    # ------------------------------------------------------------------
    # APS + native sync wrappers
    # ------------------------------------------------------------------

    async def create_task_synced(
        self, manager: SchedulerManager, task_create: ScheduledTaskCreate
    ) -> ScheduledTask:
        async with self._async_lock:
            task = await manager.create_task(task_create)
            if task_create.system_scope is None:
                return task
            scope = SystemTaskScope(task_create.system_scope)
            result = await self._reconcile_task_locked(
                manager, task.id, prior_scope=None
            )
            if result.action != "error" and result.native_error is None:
                return task

            absent, clean_err = await self._ensure_scope_absent(task.id, scope)
            if not absent:
                self._persist_reg_error(
                    task.id,
                    f"create native failed ({result.native_error or result.detail}); "
                    f"cleanup not confirmed: {clean_err}",
                )
                raise RuntimeError(
                    f"native registration failed and cleanup could not be verified "
                    f"for {task.id}: {result.native_error or result.detail}; "
                    f"cleanup={clean_err}"
                )

            try:
                cleaned = await manager.delete_task(task.id)
            except Exception as cleanup_err:
                raise RuntimeError(
                    f"native registration failed and APS cleanup failed "
                    f"for {task.id}: native={result.native_error or result.detail}; "
                    f"cleanup={cleanup_err}"
                ) from cleanup_err
            if not cleaned:
                raise RuntimeError(
                    f"native registration failed and APS cleanup failed "
                    f"for {task.id}: native={result.native_error or result.detail}; "
                    f"cleanup=delete returned false"
                )
            state = self._load_state()
            reg = self._find_record(state, task.id)
            if reg is not None:
                state.records.remove(reg)
                self._save_state(state)
            raise RuntimeError(
                f"native registration failed for {task.id}: "
                f"{result.native_error or result.detail}"
            )

    async def update_task_synced(
        self,
        manager: SchedulerManager,
        task_id: str,
        task_update: ScheduledTaskUpdate,
    ) -> TaskUpdateSyncedResult:
        async with self._async_lock:
            try:
                pre = await manager.get_task(task_id)
            except SchedulerJobDecodeError as e:
                return TaskUpdateSyncedResult(
                    task=None,
                    aps_outcome="error",
                    aps_error=f"APS job decode failed before update: {e}",
                )
            if pre is None:
                return TaskUpdateSyncedResult(task=None, aps_outcome="not_found")

            had_scope_key = manager.job_has_system_scope_key(task_id)
            state = self._load_state()
            existing = self._find_record(state, task_id)
            existing_scope = existing.last_known_scope if existing else None
            prior_scope = existing_scope

            fields = task_update.model_fields_set
            effective_update = task_update
            if (
                "system_scope" not in fields
                and had_scope_key is False
                and existing is not None
                and existing.state in ("active", "error")
                and existing_scope is not None
            ):
                injected = task_update.model_dump(exclude_unset=True)
                injected["system_scope"] = existing_scope.value
                effective_update = ScheduledTaskUpdate(**injected)

            try:
                task = await manager.update_task(task_id, effective_update)
            except SchedulerJobDecodeError as e:
                return TaskUpdateSyncedResult(
                    task=None,
                    aps_outcome="error",
                    aps_error=f"APS update decode failed: {e}",
                )
            except Exception as e:
                return TaskUpdateSyncedResult(
                    task=None,
                    aps_outcome="error",
                    aps_error=f"APS update failed: {e}",
                )
            if task is None:
                post = (
                    manager.scheduler.get_job(task_id) if manager.scheduler else None
                )
                if post is None:
                    return TaskUpdateSyncedResult(task=None, aps_outcome="not_found")
                return TaskUpdateSyncedResult(
                    task=None,
                    aps_outcome="error",
                    aps_error="APS update returned None with job still present",
                )

            if "system_scope" in fields and task_update.system_scope is None:
                prior_scope = existing_scope

            rec = await self._reconcile_task_locked(
                manager, task_id, prior_scope=prior_scope
            )
            native_status = await self._status_snapshot_locked(task_id, manager)
            return TaskUpdateSyncedResult(
                task=task,
                aps_outcome="success",
                native_status=native_status,
                native_error=rec.native_error
                or (rec.detail if rec.action == "error" else None),
            )

    async def delete_task_synced(
        self, manager: SchedulerManager, task_id: str
    ) -> bool:
        async with self._async_lock:
            state = self._load_state()
            if state.corrupt:
                raise RuntimeError(
                    "system_tasks.json corrupt; refusing task deletion"
                )
            prior_reg = self._find_record(state, task_id)
            prior_snap = prior_reg.model_copy(deep=True) if prior_reg else None

            scopes = self._tracked_scopes_for_reg(prior_reg)
            if not prior_reg:
                scopes = [SystemTaskScope.USER, SystemTaskScope.SYSTEM]
            for scope in scopes:
                ok, err = await self._ensure_scope_absent(task_id, scope)
                if not ok:
                    if prior_snap is not None:
                        self._persist_reg_error(
                            task_id, f"delete native cleanup incomplete: {err}"
                        )
                    else:
                        self._upsert_error_record(
                            task_id,
                            f"delete native cleanup incomplete (no prior record): {err}",
                        )
                    raise RuntimeError(
                        f"partial delete failure: native cleanup incomplete "
                        f"for {task_id}/{scope.value}: {err}"
                    )

            outcome = await manager.delete_task_classified(task_id)
            if outcome in ("success", "not_found"):
                state = self._load_state()
                reg = self._find_record(state, task_id)
                if reg is not None:
                    state.records.remove(reg)
                    self._save_state(state)
                return True

            msg = f"APS delete {outcome} after native cleanup"
            if prior_snap is not None:
                self._restore_reg_as_repair_after_aps_fail(prior_snap, msg)
            else:
                self._upsert_error_record(task_id, msg)
            raise RuntimeError(
                f"partial delete failure: native registration removed "
                f"but APS job delete {outcome} for {task_id}"
            )

    async def _status_snapshot_locked(
        self, task_id: str, manager: Optional[SchedulerManager] = None
    ) -> Optional[SystemTaskStatusResponse]:
        """Post-update native status snapshot (authoritative APS semantics).

        Must match get_status/list_registered: no stale last_known as active scope
        when APS is missing or system_scope=None; path_valid never forced True.
        Caller must already hold ``_async_lock``.
        """
        state = self._load_state()
        if state.corrupt:
            raise RuntimeError(
                "system_tasks.json corrupt; status unavailable. "
                f"Backup: {state.corrupt_backup}"
            )
        reg = self._find_record(state, task_id)
        if reg is None:
            return self._status_from_record(
                None,
                task_id,
                path_valid=False,
                verified=False,
                reason="no operational record",
            )
        return await self._authoritative_status_locked(
            state, reg, manager=manager, persist_obs=False
        )

    async def _cleanup_untracked_native_locked(self, task_id: str) -> None:
        for scope in (SystemTaskScope.USER, SystemTaskScope.SYSTEM):
            ok, err = await self._ensure_scope_absent(task_id, scope)
            if not ok:
                raise RuntimeError(
                    f"untracked native cleanup failed for {task_id}/{scope.value}: {err}"
                )

    # ------------------------------------------------------------------
    # status / list (read + hydrate; mutations via create/update/delete synced)
    # ------------------------------------------------------------------

    async def _authoritative_status_locked(
        self,
        state: _SystemTaskState,
        rec: SystemTaskOperationalRecord,
        *,
        manager: Optional[SchedulerManager],
        persist_obs: bool = True,
    ) -> SystemTaskStatusResponse:
        """Build authoritative status while lock is already held."""
        if state.corrupt:
            raise RuntimeError(
                "system_tasks.json corrupt; status unavailable. "
                f"Backup: {state.corrupt_backup}"
            )

        task: Optional[ScheduledTask] = None
        aps_missing = False
        aps_error: Optional[str] = None
        if manager is None:
            aps_error = "APS schedule unknown"
        else:
            try:
                task = await manager.get_task(rec.task_id)
                if task is None:
                    aps_missing = True
            except SchedulerJobDecodeError as e:
                aps_error = f"APS job decode failed: {e}"
                task = None
                aps_missing = True

        # Authoritative disabled: APS present with system_scope=None.
        if task is not None and task.system_scope is None:
            return self._status_from_record(
                rec,
                rec.task_id,
                task=task,
                aps_missing=False,
                path_valid=False,
                os_registered=False,
                verified=False,
                reason="APS system_scope is None (disabled)",
            )

        scope, _ = self._resolve_aps_scope(rec, task, aps_missing=aps_missing)
        # Authoritative registration (requires APS user/system scope).
        os_registered: Optional[bool] = None
        # Diagnostic native presence for observed (may differ when APS missing).
        diagnostic_present: Optional[bool] = None
        verified = False
        detail = aps_error or ""
        query_error = False

        if task is None:
            # APS absent/unknown: registered stays false; observe historical native.
            detail = aps_error or (
                "APS job missing" if aps_missing else "APS schedule unknown"
            )
            os_registered = False
            if rec.last_known_scope is not None:
                presence = await self._query_presence(
                    rec.task_id, rec.last_known_scope
                )
                if presence == "unknown":
                    query_error = True
                    diagnostic_present = False  # no tri-state on ObservedNativeState
                    detail = f"{detail}; native query error (unknown)"
                elif presence == "present":
                    diagnostic_present = True
                    detail = f"{detail}; historical native may still be present"
                else:
                    diagnostic_present = False
            else:
                diagnostic_present = False
        elif scope is not None:
            presence = await self._query_presence(rec.task_id, scope)
            if presence == "unknown":
                query_error = True
                detail = "native query error (unknown)"
                os_registered = None
                diagnostic_present = False
            elif presence == "present":
                os_registered = True
                diagnostic_present = True
                try:
                    exe, args = self.build_command_for_task(rec.task_id)
                    spec = SystemTaskSpec(
                        task_id=rec.task_id,
                        task_name=task.name,
                        exe_path=exe,
                        cli_args=list(args),
                        trigger=map_trigger_to_os_spec(task.trigger_config),
                        scope=scope,
                        working_dir=str(self._app_root_dir),
                    )
                    ok, vdetail = await self.backend.verify_registration(spec)
                    verified = ok
                    detail = vdetail if not ok else "verified"
                except Exception as e:
                    detail = f"verify error: {e}"
                    verified = False
            else:
                os_registered = False
                diagnostic_present = False
                detail = "native absent"
        else:
            os_registered = False
            diagnostic_present = False
            detail = detail or "APS schedule unknown"

        # Observation for active query scope only when we have one.
        obs_scope = scope or rec.last_known_scope
        if obs_scope is not None:
            obs_present = (
                bool(diagnostic_present)
                if diagnostic_present is not None
                else (bool(os_registered) if os_registered is not None else False)
            )
            new_obs = ObservedNativeState(
                scope=obs_scope,
                identifier=rec.system_task_identifier
                or self._build_identifier(rec.task_id, obs_scope),
                present=obs_present,
                # Authoritative verified only when APS-scoped registration is live.
                verified=bool(verified and os_registered is True),
                details=detail,
            )
            preserved = [o for o in rec.observed if o.scope != obs_scope]
            preserved.append(new_obs)
        else:
            preserved = list(rec.observed)

        if (
            persist_obs
            and not query_error
            and not state.corrupt
            and rec.state != "error"
            and task is not None
            and task.system_scope in ("user", "system")
        ):
            live = self._find_record(state, rec.task_id)
            if live is not None:
                live.observed = preserved
                try:
                    self._save_state(state)
                except Exception:
                    pass

        rec_view = rec.model_copy(deep=True)
        rec_view.observed = preserved
        # path_valid only when native confirmed present+verified and nonempty
        # registered_exe_path equals current APS-derived exe.
        path_valid = False
        if (
            task is not None
            and task.system_scope in ("user", "system")
            and os_registered is True
            and verified
            and rec.registered_exe_path
        ):
            exe, _ = self.build_command_for_task(rec.task_id)
            path_valid = rec.registered_exe_path == exe

        return self._status_from_record(
            rec_view,
            rec.task_id,
            task=task,
            aps_missing=aps_missing,
            path_valid=path_valid,
            # Authoritative: unknown/None → not registered.
            os_registered=False if os_registered is None else os_registered,
            verified=verified,
            reason=detail,
        )

    async def get_status(
        self, task_id: str, manager: Optional[SchedulerManager] = None
    ) -> SystemTaskStatusResponse:
        async with self._async_lock:
            state = self._load_state()
            if state.corrupt:
                raise RuntimeError(
                    "system_tasks.json corrupt; status unavailable. "
                    f"Backup: {state.corrupt_backup}"
                )
            reg = self._find_record(state, task_id)
            if not reg:
                return SystemTaskStatusResponse(
                    task_id=task_id,
                    registered=False,
                    path_valid=False,
                    reason="no operational record",
                    verified=False,
                )
            return await self._authoritative_status_locked(
                state, reg, manager=manager, persist_obs=True
            )

    async def list_registered(
        self, manager: Optional[SchedulerManager] = None
    ) -> list[SystemTaskRegistration]:
        async with self._async_lock:
            state = self._load_state()
            if state.corrupt:
                raise RuntimeError(
                    "system_tasks.json corrupt; list unavailable. "
                    f"Backup: {state.corrupt_backup}"
                )
            out: list[SystemTaskRegistration] = []
            for rec in state.records:
                status = await self._authoritative_status_locked(
                    state, rec, manager=manager, persist_obs=False
                )
                task = None
                aps_missing = False
                aps_error = None
                if manager is not None:
                    try:
                        task = await manager.get_task(rec.task_id)
                        if task is None:
                            aps_missing = True
                    except SchedulerJobDecodeError as e:
                        aps_error = f"APS job decode failed: {e}"
                        aps_missing = True
                else:
                    aps_error = "APS schedule unknown"
                out.append(
                    self._hydrate_registration(
                        rec,
                        task=task,
                        aps_missing=aps_missing,
                        aps_error=aps_error or status.reason,
                        registered=status.registered,
                        verified=status.verified,
                        path_valid=status.path_valid,
                        reason=status.reason,
                        enabled=status.enabled,
                    )
                )
            return out

    # ------------------------------------------------------------------
    # scope import + reconciler
    # ------------------------------------------------------------------

    async def import_scopes_into_aps(self, manager: SchedulerManager) -> dict:
        """Import USER/SYSTEM scope from operational/legacy records into matching APS jobs.

        Completing this method allows the first operational disk flush after a legacy load.
        """
        async with self._async_lock:
            state = self._load_state()
            if state.corrupt:
                detail = (
                    "system_tasks.json corrupt; scope import refused "
                    f"(backup={state.corrupt_backup})"
                )
                return {
                    "imported": 0,
                    "skipped": 0,
                    "missing_job": 0,
                    "failed": 1,
                    "details": [detail],
                }
            scope_by_task_id: dict[str, Literal["user", "system"]] = {}
            for rec in state.records:
                if rec.last_known_scope in (
                    SystemTaskScope.USER,
                    SystemTaskScope.SYSTEM,
                ):
                    scope_by_task_id[rec.task_id] = cast(
                        Literal["user", "system"], rec.last_known_scope.value
                    )
            stats = manager.import_system_scopes(scope_by_task_id)
            # Allow first operational write after import has consumed legacy scopes.
            state.pending_operational_flush = False
            state.version = OPERATIONAL_STATE_VERSION
            try:
                self._save_state(state)
            except Exception as e:
                logger.error("operational flush after scope import failed: %s", e)
                stats.setdefault("details", []).append(f"operational flush failed: {e}")
                stats["failed"] = int(stats.get("failed", 0)) + 1
            return stats

    async def reconcile_task(
        self,
        manager: SchedulerManager,
        task_id: str,
        prior_scope: Optional[SystemTaskScope] = None,
    ) -> ReconcileTaskResult:
        async with self._async_lock:
            return await self._reconcile_task_locked(
                manager, task_id, prior_scope=prior_scope
            )

    async def reconcile_all(self, manager: Optional[SchedulerManager] = None) -> dict:
        if manager is None:
            raise ValueError("reconcile_all requires SchedulerManager")
        async with self._async_lock:
            return await self._reconcile_all_locked(manager)

    async def repair_all(self, manager: Optional[SchedulerManager] = None) -> dict:
        return await self.reconcile_all(manager)

    async def _reconcile_all_locked(self, manager: SchedulerManager) -> dict:
        state = self._load_state()
        if state.corrupt:
            return {
                "repaired": 0,
                "failed": 1,
                "details": ["state corrupt; repair refused"],
            }

        ids: set[str] = set()
        for rec in state.records:
            ids.add(rec.task_id)
        if manager.scheduler is not None:
            for job in manager.scheduler.get_jobs():
                kwargs = job.kwargs or {}
                if "system_scope" in kwargs:
                    ids.add(job.id)

        repaired = 0
        failed = 0
        details: list[str] = []
        for task_id in sorted(ids):
            rec = await self._reconcile_task_locked(manager, task_id)
            if rec.action == "error":
                failed += 1
                details.append(f"{task_id}: {rec.detail}")
            elif rec.action in (
                "registered",
                "updated",
                "cleaned",
                "materialized",
            ):
                repaired += 1
                details.append(f"{task_id}: {rec.action} — {rec.detail}")
            elif rec.detail:
                details.append(f"{task_id}: {rec.action} — {rec.detail}")

        logger.info(
            "系统任务 reconcile 完成: repaired=%s failed=%s", repaired, failed
        )
        return {"repaired": repaired, "failed": failed, "details": details}

    async def _reconcile_task_locked(
        self,
        manager: SchedulerManager,
        task_id: str,
        prior_scope: Optional[SystemTaskScope] = None,
    ) -> ReconcileTaskResult:
        state = self._load_state()
        if state.corrupt:
            return ReconcileTaskResult(
                task_id=task_id,
                action="error",
                detail="state corrupt; reconcile refused",
                native_error="state corrupt",
            )

        reg = self._find_record(state, task_id)
        try:
            task = await manager.get_task(task_id)
            aps_decode_error: Optional[str] = None
        except SchedulerJobDecodeError as e:
            task = None
            aps_decode_error = str(e)

        if aps_decode_error is not None:
            msg = f"APS job decode failed: {aps_decode_error}"
            if reg is not None:
                self._persist_reg_error(task_id, msg)
            else:
                self._upsert_error_record(task_id, msg)
            return ReconcileTaskResult(
                task_id=task_id, action="error", detail=msg, native_error=msg
            )

        if task is None:
            if reg is None:
                try:
                    await self._cleanup_untracked_native_locked(task_id)
                except Exception as e:
                    return ReconcileTaskResult(
                        task_id=task_id,
                        action="error",
                        detail=str(e),
                        native_error=str(e),
                    )
                return ReconcileTaskResult(
                    task_id=task_id, action="noop", detail="no APS job and no record"
                )
            return await self._reconcile_orphan_cleanup_locked(task_id, reg)

        has_key = manager.job_has_system_scope_key(task_id)
        scope_val = task.system_scope

        if has_key is True:
            if scope_val is None:
                return await self._reconcile_explicit_none_locked(
                    task_id, reg, prior_scope
                )
            if scope_val not in ("user", "system"):
                msg = f"invalid system_scope on APS job: {scope_val!r}"
                if reg is not None:
                    self._persist_reg_error(task_id, msg)
                else:
                    self._upsert_error_record(task_id, msg)
                return ReconcileTaskResult(
                    task_id=task_id, action="error", detail=msg, native_error=msg
                )
            return await self._reconcile_ensure_native_locked(
                manager, task, reg, prior_scope=prior_scope
            )

        if reg is not None:
            return await self._reconcile_explicit_none_locked(
                task_id, reg, prior_scope
            )
        return ReconcileTaskResult(
            task_id=task_id, action="noop", detail="APS has no system scope key"
        )

    async def _reconcile_orphan_cleanup_locked(
        self, task_id: str, reg: SystemTaskOperationalRecord
    ) -> ReconcileTaskResult:
        scopes = self._tracked_scopes_for_reg(reg)
        for sc in (SystemTaskScope.USER, SystemTaskScope.SYSTEM):
            if sc not in scopes:
                scopes.append(sc)
        for scope in scopes:
            ok, err = await self._ensure_scope_absent(task_id, scope)
            if not ok:
                self._persist_reg_error(
                    task_id, f"orphan cleanup incomplete: {err}"
                )
                return ReconcileTaskResult(
                    task_id=task_id,
                    action="error",
                    detail=f"orphan cleanup incomplete: {err}",
                    native_error=err,
                )
        state = self._load_state()
        cur = self._find_record(state, task_id)
        if cur is not None:
            state.records.remove(cur)
            self._save_state(state)
        return ReconcileTaskResult(
            task_id=task_id,
            action="cleaned",
            detail="orphan record removed after native absence",
        )

    async def _reconcile_explicit_none_locked(
        self,
        task_id: str,
        reg: Optional[SystemTaskOperationalRecord],
        prior_scope: Optional[SystemTaskScope],
    ) -> ReconcileTaskResult:
        scopes = self._tracked_scopes_for_reg(reg, prior_scope=prior_scope)
        if not scopes:
            scopes = [SystemTaskScope.USER, SystemTaskScope.SYSTEM]
        for scope in scopes:
            ok, err = await self._ensure_scope_absent(task_id, scope)
            if not ok:
                if reg is not None:
                    self._persist_reg_error(
                        task_id, f"scope disable cleanup incomplete: {err}"
                    )
                return ReconcileTaskResult(
                    task_id=task_id,
                    action="error",
                    detail=f"cleanup incomplete: {err}",
                    native_error=err,
                )
        state = self._load_state()
        cur = self._find_record(state, task_id)
        if cur is not None:
            state.records.remove(cur)
            self._save_state(state)
            return ReconcileTaskResult(
                task_id=task_id,
                action="cleaned",
                detail="native cleaned; operational record removed",
            )
        return ReconcileTaskResult(
            task_id=task_id, action="cleaned", detail="native cleaned; no record"
        )

    async def _reconcile_ensure_native_locked(
        self,
        manager: SchedulerManager,
        task: ScheduledTask,
        reg: Optional[SystemTaskOperationalRecord],
        *,
        prior_scope: Optional[SystemTaskScope],
    ) -> ReconcileTaskResult:
        assert task.system_scope in ("user", "system")
        aps_scope = SystemTaskScope(task.system_scope)
        task_id = task.id
        try:
            aps_os_trigger = map_trigger_to_os_spec(task.trigger_config)
        except Exception as e:
            msg = f"APS trigger map failed: {e}"
            if reg is not None:
                self._persist_reg_error(task_id, msg)
            else:
                self._upsert_error_record(task_id, msg, scope=aps_scope)
            return ReconcileTaskResult(
                task_id=task_id, action="error", detail=msg, native_error=msg
            )

        warnings = self._compute_registration_warnings(aps_scope, aps_os_trigger)
        current_exe, current_args = self.build_command_for_task(task_id)
        working_dir = str(self._app_root_dir)
        new_identifier = self._build_identifier(task_id, aps_scope)

        old_scopes: set[SystemTaskScope] = set()
        if prior_scope is not None and prior_scope != aps_scope:
            old_scopes.add(prior_scope)
        # Only clean historical scopes when last_known drifts away from APS scope.
        if reg is not None and reg.last_known_scope not in (None, aps_scope):
            for sc in self._union_cleanup_scopes(reg):
                if sc != aps_scope:
                    old_scopes.add(sc)

        if reg is None:
            for sc in (SystemTaskScope.USER, SystemTaskScope.SYSTEM):
                if sc == aps_scope:
                    continue
                presence = await self._query_presence(task_id, sc)
                if presence == "unknown":
                    msg = (
                        f"opposite scope query unknown before materialize: "
                        f"{sc.value}"
                    )
                    self._upsert_error_record(task_id, msg, scope=aps_scope)
                    return ReconcileTaskResult(
                        task_id=task_id,
                        action="error",
                        detail=msg,
                        native_error=msg,
                    )
                if presence == "present":
                    old_scopes.add(sc)

        for sc in old_scopes:
            ok, err = await self._ensure_scope_absent(task_id, sc)
            if not ok:
                msg = (
                    f"old scope cleanup failed "
                    f"({sc.value}→{aps_scope.value}): {err}"
                )
                if reg is not None:
                    self._persist_reg_error(task_id, msg)
                else:
                    self._upsert_error_record(task_id, msg, scope=aps_scope)
                return ReconcileTaskResult(
                    task_id=task_id, action="error", detail=msg, native_error=msg
                )

        presence = await self._query_presence(task_id, aps_scope)
        if presence == "unknown":
            msg = f"native query error (unknown) for scope {aps_scope.value}"
            if reg is not None:
                self._persist_reg_error(task_id, msg)
            else:
                self._upsert_error_record(task_id, msg, scope=aps_scope)
            return ReconcileTaskResult(
                task_id=task_id, action="error", detail=msg, native_error=msg
            )

        # Drift exclusively from APS + current command (no JSON desired mirrors).
        need = False
        reason = ""
        if presence == "absent":
            need = True
            reason = "OS 中未找到"
        elif reg is None:
            need = True
            reason = "materialize operational record"
        elif reg.registered_exe_path and reg.registered_exe_path != current_exe:
            need = True
            reason = f"路径变化: {reg.registered_exe_path} → {current_exe}"
        elif reg.last_known_scope != aps_scope or reg.state == "error":
            need = True
            reason = "APS scope/state 与原生注册不一致"
        else:
            # Verify native artifact against APS-derived spec when present.
            try:
                spec_check = SystemTaskSpec(
                    task_id=task_id,
                    task_name=task.name,
                    exe_path=current_exe,
                    cli_args=list(current_args),
                    trigger=aps_os_trigger,
                    scope=aps_scope,
                    working_dir=working_dir,
                )
                ok, detail = await self.backend.verify_registration(spec_check)
                if not ok:
                    need = True
                    reason = f"native verify failed: {detail}"
            except Exception as e:
                need = True
                reason = f"native verify error: {e}"

        if not need:
            return ReconcileTaskResult(
                task_id=task_id, action="noop", detail="already converged"
            )

        state = self._load_state()
        r = self._find_record(state, task_id)
        materialized = r is None
        if r is None:
            r = SystemTaskOperationalRecord(
                task_id=task_id,
                platform=cast(
                    Literal["windows", "macos", "linux"],
                    self.backend.platform_name,
                ),
                state="error",
                last_known_scope=aps_scope,
                cleanup_scopes=[aps_scope],
                system_task_identifier=new_identifier,
            )
            state.records.append(r)
        else:
            r.cleanup_scopes = self._union_cleanup_scopes(r, aps_scope, *old_scopes)
        self._save_state(state)

        spec = SystemTaskSpec(
            task_id=task_id,
            task_name=task.name,
            exe_path=current_exe,
            cli_args=list(current_args),
            trigger=aps_os_trigger,
            scope=aps_scope,
            working_dir=working_dir,
        )
        try:
            await self.backend.register(spec)
            ok, detail = await self.backend.verify_registration(spec)
        except Exception as e:
            ok, detail = False, str(e)

        if not ok:
            try:
                await self.backend.unregister(task_id, aps_scope)
            except Exception as ce:
                detail = f"{detail}; compensation unregister failed: {ce}"
            still = await self._query_presence(task_id, aps_scope)
            detail = f"{detail}; still_present={still}"
            self._persist_reg_error(task_id, detail)
            return ReconcileTaskResult(
                task_id=task_id,
                action="error",
                detail=detail,
                native_error=detail,
            )

        state = self._load_state()
        r = self._find_record(state, task_id)
        if r is None:
            return ReconcileTaskResult(
                task_id=task_id,
                action="error",
                detail="record missing after successful register",
                native_error="record missing after register",
            )
        r.state = "active"
        r.last_known_scope = aps_scope
        r.cleanup_scopes = self._union_cleanup_scopes(r, aps_scope)
        r.system_task_identifier = new_identifier
        r.registered_exe_path = current_exe
        r.last_registered_at = datetime.now()
        r.last_error = None
        r.warnings = list(warnings)
        r.observed = [
            ObservedNativeState(
                scope=aps_scope,
                identifier=new_identifier,
                present=True,
                verified=True,
                details="verified",
            )
        ]
        self._save_state(state)
        if materialized:
            action = "materialized"
        elif presence == "absent":
            action = "registered"
        else:
            action = "updated"
        return ReconcileTaskResult(task_id=task_id, action=action, detail=reason)


# Back-compat alias used by older tests
_SystemTaskState  # noqa: B018 — exported for tests
