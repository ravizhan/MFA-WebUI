"""
系统级计划任务编排服务（Phase 2 Oracle-hardened）。

- asyncio.Lock spans complete native mutation/recovery/repair transactions
- pending intent before native mutation; compensation preserves observed states
- Windows same-identifier scope migration: export → replace → verify → restore
- same-scope update snapshots prior definition and restores on failure
- get_status derives registered/verified from authoritative native checks
- orphans never auto-reactivated; corrupt state fail-closed
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, Optional, cast

import json_utils as json

from models.scheduler import (
    ObservedNativeState,
    OSTriggerSpec,
    SystemCapabilitiesResponse,
    SystemTaskRegistration,
    SystemTaskScope,
    SystemTaskSpec,
    SystemTaskStatusResponse,
    TriggerConfig,
)
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
    """Transactional system task service with asyncio-serialized mutations."""

    def __init__(self, app_root_dir: Path):
        self._app_root_dir = Path(app_root_dir)
        self._config_dir = self._app_root_dir / "config"
        self._state_file = self._config_dir / "system_tasks.json"
        self._backend: Optional[SystemSchedulerBackend] = None
        self._async_lock = asyncio.Lock()
        self._apscheduler_job_exists: Optional[Callable[[str], bool]] = None
        self._apscheduler_job_enabled: Optional[Callable[[str], Optional[bool]]] = None

    def set_job_probes(
        self,
        exists: Optional[Callable[[str], bool]] = None,
        enabled: Optional[Callable[[str], Optional[bool]]] = None,
    ) -> None:
        self._apscheduler_job_exists = exists
        self._apscheduler_job_enabled = enabled

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

    def _snapshot_reg(self, reg: SystemTaskRegistration) -> SystemTaskRegistration:
        return reg.model_copy(deep=True)

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
        # Authoritative: native presence only
        if os_registered is None:
            registered = False
        else:
            registered = bool(os_registered)
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
                # Unknown — not confirmed absent
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
    # public API (all mutations under asyncio.Lock)
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

        if (
            existing
            and existing.desired_scope != scope
            and existing.state
            in (
                "active",
                "error",
                "pending_register",
            )
        ):
            return await self._migrate_scope_locked(
                state, existing, task_name, trigger_spec, scope, warnings
            )

        # Same-scope update: snapshot prior healthy registration for rollback
        prior_snap: Optional[SystemTaskRegistration] = None
        prior_blob: Optional[bytes] = None
        had_prior_active = bool(
            existing and existing.state == "active" and existing.desired_scope == scope
        )
        # If native already present, export is mandatory before mutation
        native_present = False
        try:
            native_present = await self.backend.is_registered(task_id, scope)
        except Exception as e:
            raise RuntimeError(
                f"cannot determine native presence before mutation: {e}"
            ) from e
        if native_present:
            try:
                prior_blob = await self.backend.export_native_definition(task_id, scope)
            except Exception as e:
                prior_blob = None
                logger.warning("export prior definition failed: %s", e)
            if prior_blob is None:
                raise RuntimeError(
                    "existing native registration present but export/snapshot "
                    "returned None; refusing mutation"
                )
            if existing is not None:
                prior_snap = self._snapshot_reg(existing)
                had_prior_active = True
            else:
                # Durable record missing but native exists — still protect native
                had_prior_active = True
        elif had_prior_active and existing is not None:
            prior_snap = self._snapshot_reg(existing)
            try:
                prior_blob = await self.backend.export_native_definition(task_id, scope)
            except Exception as e:
                logger.warning("export prior definition failed: %s", e)
            if prior_blob is None:
                raise RuntimeError(
                    "active durable registration but native export failed; "
                    "refusing mutation"
                )

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
            await self._compensate_register_failure(
                task_id=task_id,
                scope=scope,
                error=e,
                had_prior_active=had_prior_active,
                prior_snap=prior_snap,
                prior_blob=prior_blob,
            )
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
        self,
        *,
        task_id: str,
        scope: SystemTaskScope,
        error: Exception,
        had_prior_active: bool,
        prior_snap: Optional[SystemTaskRegistration],
        prior_blob: Optional[bytes],
    ) -> None:
        observed: list[ObservedNativeState] = []
        restore_ok = False
        comp_err: Optional[str] = None

        if had_prior_active and prior_blob is not None:
            try:
                await self.backend.restore_native_definition(task_id, scope, prior_blob)
                if prior_snap is not None:
                    ok, detail = await self.backend.verify_registration(
                        self._make_spec_from_reg(prior_snap)
                    )
                    restore_ok = ok
                    observed.append(
                        ObservedNativeState(
                            scope=scope,
                            identifier=self._build_identifier(task_id, scope),
                            present=True,
                            verified=ok,
                            details=f"restored prior: {detail}",
                        )
                    )
            except Exception as re:
                comp_err = f"restore failed: {re}"
                observed.extend(
                    await self._observe_scopes(task_id, [scope], detail=comp_err)
                )
        else:
            # New registration failed: remove partial native if any
            try:
                await self.backend.unregister(task_id, scope)
            except Exception as ce:
                comp_err = f"compensation unregister failed: {ce}"
            observed.extend(
                await self._observe_scopes(
                    task_id,
                    [scope],
                    detail=comp_err or f"register failed: {error}",
                )
            )

        state = self._load_state()
        reg = self._find_registration(state, task_id)
        if reg is None:
            return
        if restore_ok and prior_snap is not None:
            # Restore durable prior desired fields
            reg.task_name = prior_snap.task_name
            reg.desired_scope = prior_snap.desired_scope
            reg.desired_trigger = prior_snap.desired_trigger
            reg.desired_exe_path = prior_snap.desired_exe_path
            reg.desired_cli_args = prior_snap.desired_cli_args
            reg.desired_working_dir = prior_snap.desired_working_dir
            reg.system_task_identifier = prior_snap.system_task_identifier
            reg.registered_exe_path = prior_snap.registered_exe_path
            reg.state = "active"
            reg.pending_operation = "none"
            reg.last_error = f"update failed, prior restored: {error}"
            reg.observed = observed
            reg.scope = prior_snap.desired_scope
            reg.trigger_spec = prior_snap.desired_trigger
        else:
            reg.state = "error"
            reg.pending_operation = "register"
            reg.last_error = f"{error}" + (f"; {comp_err}" if comp_err else "")
            reg.observed = observed
        self._save_state(state)

    async def _migrate_scope_locked(
        self,
        state: _SystemTaskState,
        reg: SystemTaskRegistration,
        task_name: str,
        trigger_spec: OSTriggerSpec,
        new_scope: SystemTaskScope,
        warnings: list[str],
    ) -> SystemTaskStatusResponse:
        old_scope = reg.desired_scope
        task_id = reg.task_id
        exe_path, cli_args = self.build_command_for_task(task_id)
        new_id = self._build_identifier(task_id, new_scope)
        same_id = self.backend.same_native_identifier_across_scopes()

        prior_snap = self._snapshot_reg(reg)
        prior_blob: Optional[bytes] = None
        try:
            prior_blob = await self.backend.export_native_definition(task_id, old_scope)
        except Exception as e:
            logger.warning("export prior for migrate failed: %s", e)
        # Same-ID Windows migration: rollback artifact is mandatory
        if prior_blob is None:
            # Check if native actually exists
            try:
                exists_native = await self.backend.is_registered(task_id, old_scope)
            except Exception as e:
                exists_native = True  # unknown -> refuse
                logger.warning("is_registered during migrate failed: %s", e)
            if exists_native or self.backend.same_native_identifier_across_scopes():
                reg.state = "error"
                reg.pending_operation = "migrate"
                reg.last_error = (
                    "migration refused: cannot export prior native definition "
                    "for rollback"
                )
                self._save_state(state)
                raise RuntimeError(reg.last_error)

        reg.task_name = task_name
        reg.migration_from_scope = old_scope
        reg.desired_scope = new_scope
        reg.desired_trigger = trigger_spec
        reg.desired_exe_path = exe_path
        reg.desired_cli_args = cli_args
        reg.state = "pending_register"
        reg.pending_operation = "migrate"
        reg.system_task_identifier = new_id
        reg.warnings = warnings
        reg.scope = new_scope
        reg.trigger_spec = trigger_spec
        self._save_state(state)

        new_spec = SystemTaskSpec(
            task_id=task_id,
            task_name=task_name,
            exe_path=exe_path,
            cli_args=cli_args,
            trigger=trigger_spec,
            scope=new_scope,
            working_dir=str(self._app_root_dir),
        )
        observed: list[ObservedNativeState] = []
        try:
            # Collision-safe: for shared identifier, replacement overwrites
            # the same native object; do NOT register-then-delete same ID.
            await self.backend.register(new_spec)
            ok, detail = await self.backend.verify_registration(new_spec)
            if not ok:
                raise RuntimeError(f"migrate verify failed: {detail}")
            observed.append(
                ObservedNativeState(
                    scope=new_scope,
                    identifier=new_id,
                    present=True,
                    verified=True,
                    details=detail,
                )
            )
            if not same_id:
                await self.backend.unregister(task_id, old_scope)
                old_present = await self.backend.is_registered(task_id, old_scope)
                if old_present:
                    raise RuntimeError("old registration still present after migrate")
                observed.append(
                    ObservedNativeState(
                        scope=old_scope,
                        identifier=self._build_identifier(task_id, old_scope),
                        present=False,
                        verified=True,
                        details="removed",
                    )
                )
            else:
                # Shared identifier: exactly one observed native registration
                observed = [
                    ObservedNativeState(
                        scope=new_scope,
                        identifier=new_id,
                        present=True,
                        verified=True,
                        details=f"replaced in-place: {detail}",
                    )
                ]
        except Exception as e:
            # Restore prior definition and verify.
            # For distinct-ID platforms, also best-effort unregister the new target
            # that was just created so it doesn't become an orphan.
            restore_detail = ""
            if not same_id:
                try:
                    await self.backend.unregister(task_id, new_scope)
                    restore_detail = "new target unregistered; "
                except Exception as ue:
                    restore_detail = f"new target unregister failed: {ue}; "
            try:
                if prior_blob is not None:
                    await self.backend.restore_native_definition(
                        task_id, old_scope, prior_blob
                    )
                    ok, detail = await self.backend.verify_registration(
                        self._make_spec_from_reg(prior_snap)
                    )
                    restore_detail += f"restore ok={ok}: {detail}"
                else:
                    restore_detail += "no prior blob to restore"
            except Exception as re:
                restore_detail += f"; restore failed: {re}"
            observed.extend(
                await self._observe_scopes(
                    task_id,
                    list({old_scope, new_scope}),
                    detail=f"migrate failure; {restore_detail}",
                )
            )
            state = self._load_state()
            reg2 = self._find_registration(state, task_id)
            if reg2:
                # Restore durable prior desired
                reg2.task_name = prior_snap.task_name
                reg2.desired_scope = prior_snap.desired_scope
                reg2.desired_trigger = prior_snap.desired_trigger
                reg2.desired_exe_path = prior_snap.desired_exe_path
                reg2.desired_cli_args = prior_snap.desired_cli_args
                reg2.desired_working_dir = prior_snap.desired_working_dir
                reg2.system_task_identifier = prior_snap.system_task_identifier
                reg2.migration_from_scope = None
                reg2.scope = prior_snap.desired_scope
                reg2.trigger_spec = prior_snap.desired_trigger
                reg2.state = "error"
                reg2.pending_operation = "migrate"
                reg2.last_error = f"{e}; {restore_detail}"
                reg2.observed = observed
                self._save_state(state)
            raise

        state = self._load_state()
        reg3 = self._find_registration(state, task_id)
        if reg3 is None:
            raise RuntimeError("missing reg after migrate")
        reg3.state = "active"
        reg3.pending_operation = "none"
        reg3.migration_from_scope = None
        reg3.registered_exe_path = exe_path
        reg3.last_registered_at = datetime.now()
        reg3.observed = [o for o in observed if o.present]
        reg3.last_error = None
        self._save_state(state)
        return self._status_from_reg(
            reg3, task_id, path_valid=True, os_registered=True, verified=True
        )

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
            still = []
            for sc in scopes:
                if await self.backend.is_registered(task_id, sc):
                    still.append(sc)
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
                pass  # detail already set; do not claim absence
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

            # Preserve migration/error observations; only update desired scope slot
            # present=False only when confirmed absent; None/unknown -> present=False
            # but details must say unknown, never "native absent" certainty
            new_obs = ObservedNativeState(
                scope=reg_copy.desired_scope,
                identifier=reg_copy.system_task_identifier
                or self._build_identifier(task_id, reg_copy.desired_scope),
                present=bool(os_registered) if os_registered is not None else False,
                verified=verified and bool(os_registered),
                details=detail,
            )
            preserved: list[ObservedNativeState] = []
            for o in reg_copy.observed:
                if o.scope != reg_copy.desired_scope:
                    preserved.append(o)
            preserved.append(new_obs)

            # Do not overwrite durable state on status poll except observed.
            # Never persist confirmed-absent certainty from a query exception.
            if (
                not query_error
                and not state.corrupt
                and reg.state
                not in (
                    "pending_register",
                    "pending_cleanup",
                    "error",
                )
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
            # Use fresh observed for response
            reg_for_status = reg.model_copy(deep=True)
            reg_for_status.observed = preserved
            # Unknown query => registered=False is NOT claimed as confirmed absence;
            # last_error/details carry unknown. Do not persist certainty of absence.
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
            state = self._load_state()
            return list(state.registrations)

    async def mark_orphaned(self, task_id: str) -> None:
        """Persist orphan intent. Raises if state corrupt (fail closed)."""
        async with self._async_lock:
            state = self._load_state()
            if state.corrupt:
                raise RuntimeError("system_tasks.json corrupt; cannot mark orphaned")
            reg = self._find_registration(state, task_id)
            if reg:
                reg.state = "orphaned"
                reg.orphaned = True
                reg.pending_operation = "none"
                self._save_state(state)
                logger.info("系统任务 %s 已标记为孤儿", task_id)

    async def begin_orphan_before_delete(self, task_id: str) -> bool:
        """Persist orphan intent before APS deletion. Snapshots prior state.

        Returns True if a registration was marked. Raises on corrupt state.
        """
        async with self._async_lock:
            state = self._load_state()
            if state.corrupt:
                raise RuntimeError("system_tasks.json corrupt; refusing task deletion")
            reg = self._find_registration(state, task_id)
            if not reg:
                return False
            # Snapshot exact prior durable fields into last_error as JSON marker
            # (lightweight) + in-memory attribute for restore
            self._orphan_prior_snapshots = getattr(self, "_orphan_prior_snapshots", {})
            self._orphan_prior_snapshots[task_id] = {
                "state": reg.state,
                "orphaned": reg.orphaned,
                "pending_operation": reg.pending_operation,
                "last_error": reg.last_error,
            }
            reg.state = "orphaned"
            reg.orphaned = True
            reg.pending_operation = "none"
            self._save_state(state)
            return True

    async def restore_active_after_failed_delete(self, task_id: str) -> None:
        """If APS deletion failed after orphan intent, restore exact prior state."""
        async with self._async_lock:
            state = self._load_state()
            if state.corrupt:
                return
            reg = self._find_registration(state, task_id)
            if not reg:
                return
            snaps = getattr(self, "_orphan_prior_snapshots", {})
            prior = snaps.pop(task_id, None)
            if prior is None:
                # No snapshot — do NOT unconditionally reactivate
                return
            # Only restore if we actually marked orphan from this path
            if reg.state != "orphaned":
                return
            reg.state = prior["state"]
            reg.orphaned = prior["orphaned"]
            reg.pending_operation = prior["pending_operation"]
            reg.last_error = prior.get("last_error")
            if reg.state == "active":
                reg.last_error = "APS delete failed; restored prior active"
            self._save_state(state)

    async def recover_pending(self) -> dict:
        async with self._async_lock:
            return await self._recover_pending_locked()

    async def _recover_pending_locked(self) -> dict:
        state = self._load_state()
        if state.corrupt:
            return {
                "recovered": 0,
                "failed": 0,
                "details": ["state corrupt; recovery skipped"],
            }
        pending_ids = [
            (r.task_id, r.state, r.pending_operation)
            for r in state.registrations
            if r.state in ("pending_register", "pending_cleanup", "error")
            or r.pending_operation not in ("none", None)
        ]
        recovered = 0
        failed = 0
        details: list[str] = []

        for task_id, st, op in pending_ids:
            try:
                state = self._load_state()
                reg = self._find_registration(state, task_id)
                if not reg:
                    continue
                reg_snap = reg.model_copy(deep=True)

                if (
                    reg_snap.pending_operation == "unregister"
                    or st == "pending_cleanup"
                ):
                    # complete cleanup without re-entering outer lock
                    try:
                        # inline unregister steps
                        scopes = {reg_snap.desired_scope}
                        for sc in scopes:
                            await self.backend.unregister(task_id, sc)
                        still = [
                            sc
                            for sc in scopes
                            if await self.backend.is_registered(task_id, sc)
                        ]
                        if still:
                            raise RuntimeError(f"still present: {still}")
                        state = self._load_state()
                        reg = self._find_registration(state, task_id)
                        if reg:
                            state.registrations.remove(reg)
                            self._save_state(state)
                        recovered += 1
                        details.append(f"completed cleanup {task_id}")
                    except Exception as e:
                        observed = await self._observe_scopes(
                            task_id,
                            [reg_snap.desired_scope],
                            detail=f"cleanup recovery failed: {e}",
                        )
                        state = self._load_state()
                        reg = self._find_registration(state, task_id)
                        if reg:
                            reg.state = "error"
                            reg.pending_operation = "unregister"
                            reg.last_error = str(e)
                            reg.observed = observed
                            self._save_state(state)
                        failed += 1
                        details.append(f"cleanup failed {task_id}: {e}")
                    continue

                if reg_snap.pending_operation in (
                    "register",
                    "migrate",
                    "repair",
                ) or st in ("pending_register", "error"):
                    present = await self.backend.is_registered(
                        task_id, reg_snap.desired_scope
                    )
                    if present:
                        spec = self._make_spec_from_reg(reg_snap)
                        ok, detail = await self.backend.verify_registration(spec)
                        state = self._load_state()
                        reg = self._find_registration(state, task_id)
                        if reg:
                            if ok:
                                reg.state = "active"
                                reg.pending_operation = "none"
                                reg.last_error = None
                                reg.observed = [
                                    ObservedNativeState(
                                        scope=reg.desired_scope,
                                        identifier=reg.system_task_identifier,
                                        present=True,
                                        verified=True,
                                        details=detail,
                                    )
                                ]
                                recovered += 1
                                details.append(f"promoted active {task_id}")
                            else:
                                # Do NOT swallow compensation failure
                                try:
                                    await self.backend.unregister(
                                        task_id, reg.desired_scope
                                    )
                                    comp_detail = "compensated"
                                except Exception as ce:
                                    comp_detail = f"compensation failed: {ce}"
                                observed = await self._observe_scopes(
                                    task_id,
                                    [reg.desired_scope],
                                    detail=f"verify failed: {detail}; {comp_detail}",
                                )
                                reg.state = "error"
                                reg.pending_operation = "register"
                                reg.last_error = (
                                    f"recovery verify failed: {detail}; {comp_detail}"
                                )
                                reg.observed = observed
                                failed += 1
                                details.append(f"verify failed {task_id}")
                            self._save_state(state)
                    else:
                        try:
                            spec = self._make_spec_from_reg(reg_snap)
                            await self.backend.register(spec)
                            ok, detail = await self.backend.verify_registration(spec)
                            state = self._load_state()
                            reg = self._find_registration(state, task_id)
                            if reg:
                                if ok:
                                    reg.state = "active"
                                    reg.pending_operation = "none"
                                    reg.last_error = None
                                    recovered += 1
                                    details.append(f"re-registered {task_id}")
                                else:
                                    observed = await self._observe_scopes(
                                        task_id,
                                        [reg.desired_scope],
                                        detail=detail,
                                    )
                                    reg.state = "error"
                                    reg.last_error = detail
                                    reg.observed = observed
                                    failed += 1
                                self._save_state(state)
                        except Exception as e:
                            observed = await self._observe_scopes(
                                task_id,
                                [reg_snap.desired_scope],
                                detail=f"recovery re-register failed: {e}",
                            )
                            state = self._load_state()
                            reg = self._find_registration(state, task_id)
                            if reg:
                                reg.state = "error"
                                reg.last_error = str(e)
                                reg.observed = observed
                                self._save_state(state)
                            failed += 1
                            details.append(f"recovery failed {task_id}: {e}")
            except Exception as e:
                failed += 1
                details.append(f"recovery error {task_id}: {e}")

        return {"recovered": recovered, "failed": failed, "details": details}

    async def repair_all(self) -> dict:
        async with self._async_lock:
            recovery = await self._recover_pending_locked()
            state = self._load_state()
            if state.corrupt:
                return {
                    "repaired": 0,
                    "failed": 0,
                    "details": ["state corrupt; repair refused"],
                    "recovery": recovery,
                }
            regs = [r.model_copy(deep=True) for r in state.registrations]
            repaired = 0
            failed = 0
            details: list[str] = list(recovery.get("details", []))

            for reg in regs:
                try:
                    if reg.state == "orphaned" or reg.orphaned:
                        details.append(f"skip orphan {reg.task_id}")
                        continue

                    if self._apscheduler_job_exists is not None:
                        if not self._apscheduler_job_exists(reg.task_id):
                            state = self._load_state()
                            r = self._find_registration(state, reg.task_id)
                            if r:
                                r.state = "orphaned"
                                r.orphaned = True
                                r.pending_operation = "none"
                                self._save_state(state)
                            details.append(f"orphaned missing job {reg.task_id}")
                            continue

                    if self._apscheduler_job_enabled is not None:
                        enabled = self._apscheduler_job_enabled(reg.task_id)
                        if enabled is False and reg.state == "active":
                            details.append(f"active-but-disabled {reg.task_id}")

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

                    prior_blob = None
                    export_failed = False
                    try:
                        prior_blob = await self.backend.export_native_definition(
                            reg.task_id, reg.desired_scope
                        )
                    except Exception:
                        export_failed = True
                        prior_blob = None

                    # If native exists but export failed or returned None, refuse to
                    # overwrite — we cannot roll back.  Persist error/pending and skip.
                    if os_registered and prior_blob is None:
                        state = self._load_state()
                        r = self._find_registration(state, reg.task_id)
                        if r and r.state not in ("orphaned",):
                            r.state = "error"
                            r.pending_operation = "repair"
                            r.last_error = (
                                "export of prior native definition failed; "
                                "refusing to overwrite"
                            )
                            self._save_state(state)
                        failed += 1
                        reason_detail = (
                            "export exception"
                            if export_failed
                            else "export returned None"
                        )
                        details.append(
                            f"修复 {reg.task_id} 跳过: 无法导出当前原生定义 ({reason_detail})"
                        )
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
                    had_prior_native = True  # we know native exists + blob was saved
                    try:
                        await self.backend.register(spec)
                        ok, detail = await self.backend.verify_registration(spec)
                    except Exception as e:
                        ok, detail = False, str(e)

                    if not ok:
                        # Restore prior if existed; else remove invalid replacement
                        try:
                            if had_prior_native and prior_blob is not None:
                                await self.backend.restore_native_definition(
                                    reg.task_id, reg.desired_scope, prior_blob
                                )
                                # verify restore
                                try:
                                    (
                                        rok,
                                        rdetail,
                                    ) = await self.backend.verify_registration(
                                        SystemTaskSpec(
                                            task_id=reg.task_id,
                                            task_name=reg.task_name,
                                            exe_path=reg.desired_exe_path
                                            or current_exe,
                                            cli_args=list(
                                                reg.desired_cli_args or current_args
                                            ),
                                            trigger=reg.desired_trigger,
                                            scope=reg.desired_scope,
                                            working_dir=str(self._app_root_dir),
                                        )
                                    )
                                    detail = f"{detail}; restore ok={rok}: {rdetail}"
                                except Exception as re:
                                    detail = f"{detail}; restore verify failed: {re}"
                            else:
                                await self.backend.unregister(
                                    reg.task_id, reg.desired_scope
                                )
                                still = await self.backend.is_registered(
                                    reg.task_id, reg.desired_scope
                                )
                                detail = (
                                    f"{detail}; removed invalid replacement, "
                                    f"still_present={still}"
                                )
                        except Exception as ce:
                            detail = f"{detail}; compensation failed: {ce}"

                    state = self._load_state()
                    r = self._find_registration(state, reg.task_id)
                    if r:
                        if ok:
                            r.state = "active"
                            r.pending_operation = "none"
                            r.registered_exe_path = current_exe
                            r.last_registered_at = datetime.now()
                            r.last_error = None
                            repaired += 1
                            details.append(f"修复 {reg.task_id}: {reason}")
                        else:
                            observed = await self._observe_scopes(
                                reg.task_id,
                                [reg.desired_scope],
                                detail=detail,
                            )
                            r.state = "error"
                            r.pending_operation = "repair"
                            r.last_error = detail
                            r.observed = observed
                            failed += 1
                            details.append(f"修复验证失败 {reg.task_id}: {detail}")
                        self._save_state(state)
                except Exception as e:
                    failed += 1
                    details.append(f"修复 {reg.task_id} 失败: {e}")
                    logger.error("修复系统任务 %s 失败: %s", reg.task_id, e)
                    state = self._load_state()
                    r = self._find_registration(state, reg.task_id)
                    if r:
                        try:
                            observed = await self._observe_scopes(
                                reg.task_id,
                                [reg.desired_scope],
                                detail=str(e),
                            )
                            r.observed = observed
                        except Exception:
                            pass
                        r.state = "error"
                        r.last_error = str(e)
                        try:
                            self._save_state(state)
                        except Exception:
                            pass

            result = {
                "repaired": repaired,
                "failed": failed,
                "details": details,
                "recovery": recovery,
            }
            logger.info("系统任务修复完成: 修复 %s 个, 失败 %s 个", repaired, failed)
            return result
