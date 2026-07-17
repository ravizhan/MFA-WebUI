"""
系统级计划任务编排服务（低复杂度）。

- asyncio.Lock serializes native mutations
- register+verify / unregister+verify; durable error/repair state
- no exact native rollback, crash recovery, orphan intent, or APS probes
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional, cast

import json_utils as json

from models.scheduler import (
    ObservedNativeState,
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
    SystemCapabilitiesResponse,
    SystemTaskRegistration,
    SystemTaskScope,
    SystemTaskSpec,
    SystemTaskStatusResponse,
    TriggerConfig,
)
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

_STATE_VERSION = 2


class _SystemTaskState:
    def __init__(self, version: int = _STATE_VERSION):
        self.version = version
        self.registrations: list[SystemTaskRegistration] = []
        self.corrupt: bool = False
        self.corrupt_backup: Optional[Path] = None


class SystemTaskService:
    """Native system-task service with asyncio-serialized mutations."""

    def __init__(self, app_root_dir: Path):
        self._app_root_dir = Path(app_root_dir)
        self._config_dir = self._app_root_dir / "config"
        self._state_file = self._config_dir / "system_tasks.json"
        self._backend: Optional[SystemSchedulerBackend] = None
        self._async_lock = asyncio.Lock()

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
    # persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> _SystemTaskState:
        if not self._state_file.exists():
            return _SystemTaskState()
        try:
            with self._state_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("state root must be object")
            state = _SystemTaskState(version=data.get("version", _STATE_VERSION))
            for reg_data in data.get("registrations", []):
                reg_data = self._migrate_reg_dict(reg_data)
                state.registrations.append(
                    SystemTaskRegistration.model_validate(reg_data)
                )
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
                    import shutil

                    shutil.copy2(self._state_file, backup)
                state.corrupt_backup = backup
            except Exception:
                pass
            return state

    def _migrate_reg_dict(self, data: dict) -> dict:
        out = dict(data)
        if "desired_scope" not in out and "scope" in out:
            out["desired_scope"] = out["scope"]
        if "desired_trigger" not in out and "trigger_spec" in out:
            out["desired_trigger"] = out["trigger_spec"]
        if "desired_exe_path" not in out:
            out["desired_exe_path"] = out.get("registered_exe_path", "")
        if "state" not in out:
            out["state"] = "orphaned" if out.get("orphaned") else "active"
        if "pending_operation" not in out:
            out["pending_operation"] = "none"
        if "desired_cli_args" not in out:
            out["desired_cli_args"] = []
        if "desired_working_dir" not in out:
            out["desired_working_dir"] = str(self._app_root_dir)
        return out

    def _save_state(self, state: _SystemTaskState) -> None:
        if state.corrupt:
            raise RuntimeError(
                "system_tasks.json is corrupt; refusing to overwrite. "
                f"Backup: {state.corrupt_backup}"
            )
        self._config_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "version": _STATE_VERSION,
            "registrations": [
                reg.model_dump(mode="json") for reg in state.registrations
            ],
        }
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

    def _find_registration(
        self, state: _SystemTaskState, task_id: str
    ) -> Optional[SystemTaskRegistration]:
        for reg in state.registrations:
            if reg.task_id == task_id:
                return reg
        return None

    def _build_identifier(self, task_id: str, scope: SystemTaskScope) -> str:
        return self.backend.build_identifier(task_id, scope)

    def _make_spec_from_reg(self, reg: SystemTaskRegistration) -> SystemTaskSpec:
        exe, args = self.build_command_for_task(reg.task_id)
        if reg.desired_exe_path and reg.desired_cli_args:
            exe, args = reg.desired_exe_path, list(reg.desired_cli_args)
        return SystemTaskSpec(
            task_id=reg.task_id,
            task_name=reg.task_name,
            exe_path=exe,
            cli_args=args,
            trigger=reg.desired_trigger,
            scope=reg.desired_scope,
            working_dir=reg.desired_working_dir or str(self._app_root_dir),
        )

    def _status_from_reg(
        self,
        reg: Optional[SystemTaskRegistration],
        task_id: str,
        *,
        path_valid: bool = True,
        os_registered: Optional[bool] = None,
        verified: Optional[bool] = None,
    ) -> SystemTaskStatusResponse:
        if reg is None:
            return SystemTaskStatusResponse(
                task_id=task_id,
                registered=False,
                path_valid=True,
                state=None,
                pending_operation=None,
                orphaned=False,
            )
        registered = bool(os_registered) if os_registered is not None else False
        caps = self.get_capabilities()
        enabled, reason, cap_warnings = is_capability_enabled(
            caps, reg.desired_scope, reg.desired_trigger.trigger_type
        )
        warnings = list(reg.warnings) + cap_warnings
        if verified is None:
            verified = any(o.verified and o.present for o in reg.observed)
        return SystemTaskStatusResponse(
            task_id=task_id,
            registered=registered,
            scope=reg.desired_scope,
            platform=reg.platform,
            next_run_time=None,
            last_error=reg.last_error,
            path_valid=path_valid,
            state=reg.state,
            pending_operation=reg.pending_operation,
            orphaned=reg.state == "orphaned" or reg.orphaned,
            desired_scope=reg.desired_scope,
            observed=list(reg.observed),
            warnings=warnings,
            enabled=enabled,
            verified=verified,
            reason=reason if not enabled else "",
        )

    async def _observe_scopes(
        self, task_id: str, scopes: list[SystemTaskScope], *, detail: str
    ) -> list[ObservedNativeState]:
        observed: list[ObservedNativeState] = []
        for sc in scopes:
            try:
                present = await self.backend.is_registered(task_id, sc)
                d = detail
            except Exception as e:
                present = False
                d = f"{detail}; native query error (unknown): {e}"
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
            try:
                await self._register_locked(
                    task.id, task.name, task.trigger_config, scope
                )
            except Exception as native_err:
                try:
                    cleaned = await manager.delete_task(task.id)
                except Exception as cleanup_err:
                    raise RuntimeError(
                        f"native registration failed and APS cleanup failed "
                        f"for {task.id}: native={native_err}; cleanup={cleanup_err}"
                    ) from native_err
                if not cleaned:
                    raise RuntimeError(
                        f"native registration failed and APS cleanup failed "
                        f"for {task.id}: native={native_err}; cleanup=delete returned false"
                    ) from native_err
                try:
                    native_present = await self.backend.is_registered(task.id, scope)
                except Exception as cleanup_err:
                    raise RuntimeError(
                        f"native registration failed and cleanup could not be verified "
                        f"for {task.id}: native={native_err}; cleanup={cleanup_err}"
                    ) from native_err
                if native_present:
                    raise RuntimeError(
                        f"native registration failed and cleanup left native task "
                        f"installed for {task.id}: {native_err}"
                    ) from native_err
                state = self._load_state()
                reg = self._find_registration(state, task.id)
                if reg is not None:
                    state.registrations.remove(reg)
                    self._save_state(state)
                raise
            return task

    async def update_task_synced(
        self,
        manager: SchedulerManager,
        task_id: str,
        task_update: ScheduledTaskUpdate,
    ) -> Optional[ScheduledTask]:
        # system_scope: omitted=sync active/error; null=unregister; value=register
        async with self._async_lock:
            if await manager.get_task(task_id) is None:
                return None

            state = self._load_state()
            existing = self._find_registration(state, task_id)
            existing_scope = existing.desired_scope if existing else None
            existing_state = existing.state if existing else None

            task = await manager.update_task(task_id, task_update)
            if task is None:
                return None

            fields = task_update.model_fields_set
            if "system_scope" in fields:
                if task_update.system_scope is None:
                    await self._unregister_locked(task_id)
                else:
                    await self._register_locked(
                        task.id,
                        task.name,
                        task.trigger_config,
                        SystemTaskScope(task_update.system_scope),
                    )
            elif existing is not None and existing_state in ("active", "error"):
                assert existing_scope is not None
                await self._register_locked(
                    task.id, task.name, task.trigger_config, existing_scope
                )
            return task

    async def delete_task_synced(
        self, manager: SchedulerManager, task_id: str
    ) -> bool:
        async with self._async_lock:
            state = self._load_state()
            if state.corrupt:
                raise RuntimeError(
                    "system_tasks.json corrupt; refusing task deletion"
                )
            prior_reg = self._find_registration(state, task_id)
            prior_snap = prior_reg.model_copy(deep=True) if prior_reg else None
            if prior_reg is not None:
                await self._unregister_locked(task_id)
            else:
                await self._cleanup_untracked_native_locked(task_id)

            try:
                success = await manager.delete_task(task_id)
            except Exception as e:
                if prior_snap is not None:
                    self._restore_reg_as_repair_after_aps_fail(
                        prior_snap, f"APS delete raised after native cleanup: {e}"
                    )
                raise RuntimeError(
                    f"partial delete failure: native cleanup done but APS "
                    f"delete raised for {task_id}: {e}"
                ) from e

            if success:
                return True
            if prior_snap is not None:
                self._restore_reg_as_repair_after_aps_fail(
                    prior_snap,
                    "APS delete returned false after native cleanup",
                )
                raise RuntimeError(
                    f"partial delete failure: native registration removed "
                    f"but APS job delete failed for {task_id}"
                )
            return False

    async def _cleanup_untracked_native_locked(self, task_id: str) -> None:
        """Remove unmanaged native regs (no durable record) for both scopes."""
        for scope in (SystemTaskScope.USER, SystemTaskScope.SYSTEM):
            try:
                present = await self.backend.is_registered(task_id, scope)
            except Exception as e:
                raise RuntimeError(
                    f"untracked native query failed for {task_id}/{scope.value}: {e}"
                ) from e
            if not present:
                continue
            try:
                await self.backend.unregister(task_id, scope)
                still = await self.backend.is_registered(task_id, scope)
            except Exception as e:
                raise RuntimeError(
                    f"untracked native cleanup failed for {task_id}/{scope.value}: {e}"
                ) from e
            if still:
                raise RuntimeError(
                    f"untracked native still present after unregister: "
                    f"{task_id}/{scope.value}"
                )

    def _restore_reg_as_repair_after_aps_fail(
        self, prior: SystemTaskRegistration, last_error: str
    ) -> None:
        """Re-persist prior reg as error/repair after native gone but APS delete failed."""
        state = self._load_state()
        if state.corrupt:
            return
        reg = prior.model_copy(deep=True)
        reg.state = "error"
        reg.pending_operation = "repair"
        reg.orphaned = False
        reg.last_error = last_error
        reg.observed = [
            ObservedNativeState(
                scope=reg.desired_scope,
                identifier=reg.system_task_identifier
                or self._build_identifier(reg.task_id, reg.desired_scope),
                present=False,
                verified=False,
                details="native cleaned; APS delete failed",
            )
        ]
        existing = self._find_registration(state, reg.task_id)
        if existing is not None:
            state.registrations.remove(existing)
        state.registrations.append(reg)
        self._save_state(state)

    # ------------------------------------------------------------------
    # native register / unregister
    # ------------------------------------------------------------------

    async def register(
        self,
        task_id: str,
        task_name: str,
        trigger_config: TriggerConfig,
        scope: SystemTaskScope,
    ) -> SystemTaskStatusResponse:
        async with self._async_lock:
            return await self._register_locked(
                task_id, task_name, trigger_config, scope
            )

    async def _register_locked(
        self,
        task_id: str,
        task_name: str,
        trigger_config: TriggerConfig,
        scope: SystemTaskScope,
    ) -> SystemTaskStatusResponse:
        state = self._load_state()
        if state.corrupt:
            raise RuntimeError("system_tasks.json corrupt; registration refused")

        trigger_spec = map_trigger_to_os_spec(trigger_config)
        warnings = validate_trigger_for_platform(
            self.backend.platform_name, trigger_spec
        )
        caps = self.get_capabilities()
        enabled, reason, cap_warnings = is_capability_enabled(
            caps, scope, trigger_spec.trigger_type
        )
        warnings = list(warnings) + cap_warnings
        if not enabled:
            raise ValueError(f"capability disabled: {reason}")

        exe_path, cli_args = self.build_command_for_task(task_id)
        identifier = self._build_identifier(task_id, scope)
        existing = self._find_registration(state, task_id)

        # Scope change: remove old scope first (no exact native rollback)
        if (
            existing is not None
            and existing.desired_scope != scope
            and existing.state in ("active", "error", "pending_register")
        ):
            old_scope = existing.desired_scope
            try:
                await self.backend.unregister(task_id, old_scope)
                if await self.backend.is_registered(task_id, old_scope):
                    raise RuntimeError(
                        f"old scope still present after unregister: {old_scope}"
                    )
            except Exception as e:
                existing.state = "error"
                existing.pending_operation = "register"
                existing.last_error = f"scope change unregister failed: {e}"
                existing.observed = await self._observe_scopes(
                    task_id, [old_scope, scope], detail=str(e)
                )
                self._save_state(state)
                raise

        reg = existing
        if reg is None:
            reg = SystemTaskRegistration(
                task_id=task_id,
                task_name=task_name,
                platform=cast(
                    Literal["windows", "macos", "linux"],
                    self.backend.platform_name,
                ),
                desired_scope=scope,
                desired_trigger=trigger_spec,
                desired_exe_path=exe_path,
                desired_cli_args=cli_args,
                desired_working_dir=str(self._app_root_dir),
                state="pending_register",
                pending_operation="register",
                system_task_identifier=identifier,
                registered_exe_path=exe_path,
                last_registered_at=None,
                orphaned=False,
                warnings=warnings,
                scope=scope,
                trigger_spec=trigger_spec,
            )
            state.registrations.append(reg)
        else:
            reg.task_name = task_name
            reg.desired_scope = scope
            reg.desired_trigger = trigger_spec
            reg.desired_exe_path = exe_path
            reg.desired_cli_args = cli_args
            reg.desired_working_dir = str(self._app_root_dir)
            reg.state = "pending_register"
            reg.pending_operation = "register"
            reg.system_task_identifier = identifier
            reg.orphaned = False
            reg.migration_from_scope = None
            reg.warnings = warnings
            reg.scope = scope
            reg.trigger_spec = trigger_spec
            reg.last_error = None

        self._save_state(state)

        spec = SystemTaskSpec(
            task_id=task_id,
            task_name=task_name,
            exe_path=exe_path,
            cli_args=cli_args,
            trigger=trigger_spec,
            scope=scope,
            working_dir=str(self._app_root_dir),
        )
        try:
            await self.backend.register(spec)
            ok, detail = await self.backend.verify_registration(spec)
            if not ok:
                raise RuntimeError(f"native verification failed: {detail}")
        except Exception as e:
            await self._compensate_register_failure(task_id, scope, e)
            raise

        state = self._load_state()
        reg = self._find_registration(state, task_id)
        if reg is None:
            raise RuntimeError("registration record missing after native create")
        reg.state = "active"
        reg.pending_operation = "none"
        reg.registered_exe_path = exe_path
        reg.last_registered_at = datetime.now()
        reg.last_error = None
        reg.orphaned = False
        reg.observed = [
            ObservedNativeState(
                scope=scope,
                identifier=identifier,
                present=True,
                verified=True,
                details="verified",
            )
        ]
        self._save_state(state)
        return self._status_from_reg(
            reg, task_id, path_valid=True, os_registered=True, verified=True
        )

    async def _compensate_register_failure(
        self, task_id: str, scope: SystemTaskScope, error: Exception
    ) -> None:
        """Best-effort unregister target; persist error (no prior restore)."""
        comp_parts: list[str] = []
        try:
            await self.backend.unregister(task_id, scope)
        except Exception as ce:
            comp_parts.append(f"compensation unregister failed: {ce}")
        try:
            still = await self.backend.is_registered(task_id, scope)
            if still:
                comp_parts.append("native still present after compensation unregister")
        except Exception as qe:
            still = False
            comp_parts.append(f"compensation presence query failed: {qe}")
        detail = "; ".join(comp_parts) if comp_parts else f"register failed: {error}"
        observed = await self._observe_scopes(task_id, [scope], detail=detail)
        state = self._load_state()
        reg = self._find_registration(state, task_id)
        if reg is None:
            return
        reg.state = "error"
        reg.pending_operation = "register"
        reg.last_error = f"{error}" + (f"; {detail}" if comp_parts else "")
        reg.observed = observed
        self._save_state(state)

    async def unregister(self, task_id: str) -> SystemTaskStatusResponse:
        async with self._async_lock:
            return await self._unregister_locked(task_id)

    async def _unregister_locked(self, task_id: str) -> SystemTaskStatusResponse:
        state = self._load_state()
        if state.corrupt:
            raise RuntimeError("system_tasks.json corrupt; unregister refused")
        reg = self._find_registration(state, task_id)
        if not reg:
            return SystemTaskStatusResponse(
                task_id=task_id, registered=False, path_valid=True
            )
        scopes_to_clean = {reg.desired_scope}
        if reg.migration_from_scope:
            scopes_to_clean.add(reg.migration_from_scope)
        for obs in reg.observed:
            if obs.present:
                scopes_to_clean.add(obs.scope)
        reg.state = "pending_cleanup"
        reg.pending_operation = "unregister"
        reg.last_error = None
        self._save_state(state)
        scopes = list(scopes_to_clean)

        try:
            for sc in scopes:
                await self.backend.unregister(task_id, sc)
            still = [
                sc for sc in scopes if await self.backend.is_registered(task_id, sc)
            ]
            if still:
                raise RuntimeError(
                    f"native registration still present after unregister: {still}"
                )
        except Exception as e:
            observed = await self._observe_scopes(
                task_id, scopes, detail=f"unregister failed: {e}"
            )
            state = self._load_state()
            reg = self._find_registration(state, task_id)
            if reg:
                reg.state = "error"
                reg.pending_operation = "unregister"
                reg.last_error = str(e)
                reg.observed = observed
                self._save_state(state)
            raise

        state = self._load_state()
        reg = self._find_registration(state, task_id)
        if reg:
            state.registrations.remove(reg)
            self._save_state(state)
        return SystemTaskStatusResponse(
            task_id=task_id, registered=False, path_valid=True, state=None
        )

    async def get_status(self, task_id: str) -> SystemTaskStatusResponse:
        async with self._async_lock:
            state = self._load_state()
            reg = self._find_registration(state, task_id)
            if not reg:
                return SystemTaskStatusResponse(
                    task_id=task_id, registered=False, path_valid=True
                )
            reg_copy = reg.model_copy(deep=True)

            os_registered: Optional[bool] = None
            verified = False
            query_error = False
            detail = ""
            try:
                os_registered = await self.backend.is_registered(
                    task_id, reg_copy.desired_scope
                )
            except Exception as e:
                query_error = True
                os_registered = None
                detail = f"native query error (unknown): {e}"
                logger.warning("查询系统任务 %s 状态时出错: %s", task_id, e)

            if query_error:
                pass
            elif os_registered:
                try:
                    ok, detail = await self.backend.verify_registration(
                        self._make_spec_from_reg(reg_copy)
                    )
                    verified = ok
                except Exception as e:
                    detail = f"verify error: {e}"
                    verified = False
            else:
                detail = "native absent"

            new_obs = ObservedNativeState(
                scope=reg_copy.desired_scope,
                identifier=reg_copy.system_task_identifier
                or self._build_identifier(task_id, reg_copy.desired_scope),
                present=bool(os_registered) if os_registered is not None else False,
                verified=verified and bool(os_registered),
                details=detail,
            )
            preserved = [o for o in reg_copy.observed if o.scope != reg_copy.desired_scope]
            preserved.append(new_obs)

            if (
                not query_error
                and not state.corrupt
                and reg.state not in ("pending_register", "pending_cleanup", "error")
            ):
                reg.observed = preserved
                try:
                    self._save_state(state)
                except Exception:
                    pass

            path_valid = (
                reg.desired_exe_path == self.build_command_for_task(task_id)[0]
                or reg.registered_exe_path == self.build_command_for_task(task_id)[0]
            )
            reg_for_status = reg.model_copy(deep=True)
            reg_for_status.observed = preserved
            return self._status_from_reg(
                reg_for_status,
                task_id,
                path_valid=path_valid,
                os_registered=bool(os_registered)
                if os_registered is not None
                else False,
                verified=verified and bool(os_registered),
            )

    async def list_registered(self) -> list[SystemTaskRegistration]:
        async with self._async_lock:
            return list(self._load_state().registrations)

    async def repair_all(self) -> dict:
        """Native-only repair for active/error regs (no APS probes / export / restore)."""
        async with self._async_lock:
            state = self._load_state()
            if state.corrupt:
                return {
                    "repaired": 0,
                    "failed": 0,
                    "details": ["state corrupt; repair refused"],
                }
            regs = [r.model_copy(deep=True) for r in state.registrations]
            repaired = 0
            failed = 0
            details: list[str] = []

            for reg in regs:
                try:
                    if reg.state == "orphaned" or reg.orphaned:
                        details.append(f"skip orphan {reg.task_id}")
                        continue
                    if reg.state not in ("active", "error"):
                        continue

                    os_registered = await self.backend.is_registered(
                        reg.task_id, reg.desired_scope
                    )
                    current_exe, current_args = self.build_command_for_task(reg.task_id)
                    need_repair = False
                    reason = ""
                    if not os_registered:
                        need_repair = True
                        reason = "OS 中未找到"
                    elif reg.desired_exe_path != current_exe or (
                        reg.desired_cli_args and reg.desired_cli_args != current_args
                    ):
                        need_repair = True
                        reason = f"路径变化: {reg.desired_exe_path} → {current_exe}"
                    if not need_repair:
                        continue

                    state = self._load_state()
                    r = self._find_registration(state, reg.task_id)
                    if not r or r.state == "orphaned":
                        continue
                    r.state = "pending_register"
                    r.pending_operation = "repair"
                    r.desired_exe_path = current_exe
                    r.desired_cli_args = current_args
                    self._save_state(state)

                    spec = SystemTaskSpec(
                        task_id=reg.task_id,
                        task_name=reg.task_name,
                        exe_path=current_exe,
                        cli_args=current_args,
                        trigger=reg.desired_trigger,
                        scope=reg.desired_scope,
                        working_dir=str(self._app_root_dir),
                    )
                    try:
                        await self.backend.register(spec)
                        ok, detail = await self.backend.verify_registration(spec)
                    except Exception as e:
                        ok, detail = False, str(e)

                    if not ok:
                        try:
                            await self.backend.unregister(
                                reg.task_id, reg.desired_scope
                            )
                        except Exception as ce:
                            detail = f"{detail}; compensation unregister failed: {ce}"
                        still = False
                        try:
                            still = await self.backend.is_registered(
                                reg.task_id, reg.desired_scope
                            )
                        except Exception:
                            pass
                        detail = f"{detail}; still_present={still}"

                    state = self._load_state()
                    r = self._find_registration(state, reg.task_id)
                    if not r:
                        continue
                    if ok:
                        r.state = "active"
                        r.pending_operation = "none"
                        r.registered_exe_path = current_exe
                        r.last_registered_at = datetime.now()
                        r.last_error = None
                        r.observed = [
                            ObservedNativeState(
                                scope=reg.desired_scope,
                                identifier=r.system_task_identifier
                                or self._build_identifier(
                                    reg.task_id, reg.desired_scope
                                ),
                                present=True,
                                verified=True,
                                details="verified",
                            )
                        ]
                        repaired += 1
                        details.append(f"修复 {reg.task_id}: {reason}")
                    else:
                        r.state = "error"
                        r.pending_operation = "repair"
                        r.last_error = detail
                        r.observed = await self._observe_scopes(
                            reg.task_id, [reg.desired_scope], detail=detail
                        )
                        failed += 1
                        details.append(f"修复失败 {reg.task_id}: {detail}")
                    self._save_state(state)
                except Exception as e:
                    failed += 1
                    details.append(f"修复 {reg.task_id} 失败: {e}")
                    logger.error("修复系统任务 %s 失败: %s", reg.task_id, e)
                    state = self._load_state()
                    r = self._find_registration(state, reg.task_id)
                    if r:
                        try:
                            r.observed = await self._observe_scopes(
                                reg.task_id, [reg.desired_scope], detail=str(e)
                            )
                        except Exception:
                            pass
                        r.state = "error"
                        r.last_error = str(e)
                        try:
                            self._save_state(state)
                        except Exception:
                            pass

            logger.info("系统任务修复完成: 修复 %s 个, 失败 %s 个", repaired, failed)
            return {"repaired": repaired, "failed": failed, "details": details}
