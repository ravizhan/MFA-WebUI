"""
WakeupCoordinator (SystemTaskService): APS-owned tasks + OS native wakeup adapter.

- asyncio.Lock serializes native mutations
- on-disk state is operational-only (no desired schedule mirrors)
- APS ``wakeup_enabled`` is source of truth; SystemSchedulerBackend is the
  user-level WakeupAdapter (register/verify/unregister)
- No legacy migration or multi-scope cleanup paths
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Literal, NoReturn, cast

import json_utils as json

from models.scheduler import (
    OPERATIONAL_STATE_KEYS,
    OPERATIONAL_STATE_VERSION,
    OSTriggerSpec,
    ReconcileTaskResult,
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
    SystemTaskOperationalRecord,
    SystemTaskRegistration,
    SystemTaskSpec,
    SystemTaskStatusResponse,
    TaskUpdateSyncedResult,
)
from scheduler_job_codec import SchedulerJobDecodeError
from scheduler_manager import SchedulerManager
from services.system_scheduler_backend import (
    SystemSchedulerBackend,
    build_native_command,
    get_backend,
    map_trigger_to_os_spec,
    validate_trigger_for_platform,
)

logger = logging.getLogger(__name__)


class _SystemTaskState:
    def __init__(self, version: int = OPERATIONAL_STATE_VERSION):
        self.version = version
        self.records: list[SystemTaskOperationalRecord] = []
        self.corrupt: bool = False


class SystemTaskService:
    """WakeupCoordinator: reconcile APS wakeup_enabled with native OS user wakeups."""

    def __init__(self, app_root_dir: Path):
        self._app_root_dir = Path(app_root_dir)
        self._config_dir = self._app_root_dir / "config"
        self._state_file = self._config_dir / "system_tasks.json"
        self._backend: SystemSchedulerBackend | None = None
        self._async_lock = asyncio.Lock()

    @property
    def backend(self) -> SystemSchedulerBackend:
        if self._backend is None:
            self._backend = get_backend()
        return self._backend

    def build_command_for_task(self, task_id: str) -> tuple[str, list[str]]:
        return build_native_command(self._app_root_dir, task_id)

    # ------------------------------------------------------------------
    # persistence (operational state — current schema only)
    # ------------------------------------------------------------------

    def _load_state(self) -> _SystemTaskState:
        if not self._state_file.exists():
            return _SystemTaskState(version=OPERATIONAL_STATE_VERSION)
        try:
            with self._state_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("state root must be object")
            # version is informational only; not validated on load.
            state = _SystemTaskState(version=OPERATIONAL_STATE_VERSION)
            raw_regs = data.get("registrations", [])
            if not isinstance(raw_regs, list):
                raise ValueError("registrations must be list")
            for reg_data in raw_regs:
                if not isinstance(reg_data, dict):
                    raise ValueError("registration must be object")
                missing = {"task_id", "platform", "state"} - set(reg_data.keys())
                if missing:
                    raise ValueError(f"registration missing keys: {sorted(missing)}")
                # Known keys only; unknown fields are silently ignored.
                state.records.append(
                    SystemTaskOperationalRecord.model_validate(
                        {k: reg_data[k] for k in OPERATIONAL_STATE_KEYS if k in reg_data}
                    )
                )
            return state
        except Exception as e:
            logger.error("加载 system_tasks.json 失败（fail closed）: %s", e)
            state = _SystemTaskState()
            state.corrupt = True
            return state

    def _save_state(self, state: _SystemTaskState) -> None:
        if state.corrupt:
            raise RuntimeError(
                "system_tasks.json is corrupt; refusing to overwrite"
            )
        self._config_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "version": OPERATIONAL_STATE_VERSION,
            "registrations": [rec.to_operational_dict() for rec in state.records],
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
        state.version = OPERATIONAL_STATE_VERSION

    def _find_record(
        self, state: _SystemTaskState, task_id: str
    ) -> SystemTaskOperationalRecord | None:
        for rec in state.records:
            if rec.task_id == task_id:
                return rec
        return None

    def _hydrate_registration(
        self,
        rec: SystemTaskOperationalRecord,
        *,
        task: ScheduledTask | None = None,
        registered: bool = False,
        verified: bool = False,
        path_valid: bool = False,
        reason: str | None = None,
        enabled: bool | None = None,
    ) -> SystemTaskRegistration:
        name = ""
        trigger: OSTriggerSpec | None = None
        next_run = None
        if task is not None and task.wakeup_enabled:
            name = task.name
            next_run = task.next_run_time
            try:
                trigger = map_trigger_to_os_spec(task.trigger_config)
            except Exception:
                trigger = None
        return SystemTaskRegistration(
            task_id=rec.task_id,
            task_name=name,
            platform=rec.platform,
            state=rec.state,
            registered_exe_path=rec.registered_exe_path,
            last_registered_at=rec.last_registered_at,
            last_error=rec.last_error,
            trigger_spec=trigger,
            next_run_time=next_run,
            registered=registered,
            verified=verified,
            path_valid=path_valid,
            reason=reason,
            enabled=enabled,
        )

    def _status_from_record(
        self,
        rec: SystemTaskOperationalRecord | None,
        task_id: str,
        *,
        task: ScheduledTask | None = None,
        path_valid: bool = False,
        os_registered: bool = False,
        verified: bool = False,
        reason: str | None = None,
    ) -> SystemTaskStatusResponse:
        if rec is None:
            return SystemTaskStatusResponse(
                task_id=task_id,
                registered=False,
                path_valid=False,
                state=None,
                reason=reason or "no operational record",
                verified=False,
            )

        enabled: bool | None = None
        enable_reason = ""
        if task is not None and task.wakeup_enabled:
            try:
                os_trigger = map_trigger_to_os_spec(task.trigger_config)
                validate_trigger_for_platform(self.backend.platform_name, os_trigger)
                enabled = True
            except Exception as e:
                enabled = False
                enable_reason = str(e)
        elif task is not None:
            enabled = False

        out_reason = reason or ""
        if enabled is False and enable_reason:
            out_reason = out_reason or enable_reason

        return SystemTaskStatusResponse(
            task_id=task_id,
            registered=os_registered,
            platform=rec.platform,
            task_name=task.name if task is not None else "",
            next_run_time=(
                task.next_run_time
                if task is not None and task.wakeup_enabled
                else None
            ),
            last_error=rec.last_error,
            path_valid=path_valid,
            state=rec.state,
            registered_exe_path=rec.registered_exe_path,
            enabled=enabled,
            verified=verified,
            reason=out_reason,
        )

    # ------------------------------------------------------------------
    # tri-state native query
    # ------------------------------------------------------------------

    async def _query_presence(
        self, task_id: str
    ) -> Literal["present", "absent", "unknown"]:
        try:
            present = await self.backend.is_registered(task_id)
        except Exception as e:
            logger.warning("native presence query unknown for %s: %s", task_id, e)
            return "unknown"
        return "present" if present else "absent"

    async def _ensure_absent(self, task_id: str) -> tuple[bool, str | None]:
        presence = await self._query_presence(task_id)
        if presence == "absent":
            return True, None
        if presence == "unknown":
            return False, "native query unknown"
        try:
            await self.backend.unregister(task_id)
        except Exception as e:
            return False, f"unregister failed: {e}"
        after = await self._query_presence(task_id)
        if after == "absent":
            return True, None
        if after == "unknown":
            return False, "absence query unknown after unregister"
        return False, "still present after unregister"

    @staticmethod
    def _reconcile_error(result: ReconcileTaskResult) -> str | None:
        if result.action != "error":
            return None
        return result.native_error or result.detail

    def _write_error_record_locked(
        self,
        task_id: str,
        message: str,
        *,
        mode: Literal["existing_only", "upsert", "restore"],
        prior: SystemTaskOperationalRecord | None = None,
    ) -> None:
        state = self._load_state()
        if state.corrupt:
            return
        existing = self._find_record(state, task_id)
        if mode == "existing_only":
            if existing is None:
                return
            target = existing
        elif mode == "upsert":
            if existing is None:
                target = SystemTaskOperationalRecord(
                    task_id=task_id,
                    platform=cast(
                        Literal["windows", "macos", "linux"],
                        self.backend.platform_name,
                    ),
                    state="error",
                )
                state.records.append(target)
            else:
                target = existing
        else:  # restore
            if prior is None:
                raise ValueError("restore mode requires prior record")
            target = prior.model_copy(deep=True)
            if existing is not None:
                state.records.remove(existing)
            state.records.append(target)
        target.state = "error"
        target.last_error = message
        self._save_state(state)

    def _remove_operational_record_locked(self, task_id: str) -> bool:
        state = self._load_state()
        record = self._find_record(state, task_id)
        if record is None:
            return False
        state.records.remove(record)
        self._save_state(state)
        return True

    async def _raise_after_failed_create_locked(
        self,
        manager: SchedulerManager,
        task_id: str,
        native_error: str,
    ) -> NoReturn:
        absent, clean_err = await self._ensure_absent(task_id)
        if not absent:
            self._write_error_record_locked(
                task_id,
                f"create native failed ({native_error}); "
                f"cleanup not confirmed: {clean_err}",
                mode="existing_only",
            )
            raise RuntimeError(
                f"native registration failed and cleanup could not be verified "
                f"for {task_id}: {native_error}; "
                f"cleanup={clean_err}"
            )

        try:
            cleaned = await manager.delete_task(task_id)
        except Exception as cleanup_err:
            raise RuntimeError(
                f"native registration failed and APS cleanup failed "
                f"for {task_id}: native={native_error}; "
                f"cleanup={cleanup_err}"
            ) from cleanup_err
        if not cleaned:
            raise RuntimeError(
                f"native registration failed and APS cleanup failed "
                f"for {task_id}: native={native_error}; "
                f"cleanup=delete returned false"
            )
        self._remove_operational_record_locked(task_id)
        raise RuntimeError(
            f"native registration failed for {task_id}: "
            f"{native_error}"
        )

    # ------------------------------------------------------------------
    # APS + native sync wrappers
    # ------------------------------------------------------------------

    async def create_task_synced(
        self, manager: SchedulerManager, task_create: ScheduledTaskCreate
    ) -> ScheduledTask:
        async with self._async_lock:
            task = await manager.create_task(task_create)
            if not task_create.wakeup_enabled:
                return task
            result = await self._reconcile_task_locked(manager, task.id)
            native_error = self._reconcile_error(result)
            if native_error is None:
                return task
            await self._raise_after_failed_create_locked(
                manager, task.id, native_error
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

            try:
                task = await manager.update_task(task_id, task_update)
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

            rec = await self._reconcile_task_locked(manager, task_id)
            native_status = await self._status_snapshot_locked(task_id, manager)
            return TaskUpdateSyncedResult(
                task=task,
                aps_outcome="success",
                native_status=native_status,
                native_error=self._reconcile_error(rec),
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

            ok, err = await self._ensure_absent(task_id)
            if not ok:
                if prior_snap is not None:
                    self._write_error_record_locked(
                        task_id,
                        f"delete native cleanup incomplete: {err}",
                        mode="existing_only",
                    )
                else:
                    self._write_error_record_locked(
                        task_id,
                        f"delete native cleanup incomplete (no prior record): {err}",
                        mode="upsert",
                    )
                raise RuntimeError(
                    f"partial delete failure: native cleanup incomplete "
                    f"for {task_id}: {err}"
                )

            outcome = await manager.delete_task_classified(task_id)
            if outcome in ("success", "not_found"):
                self._remove_operational_record_locked(task_id)
                return True

            msg = f"APS delete {outcome} after native cleanup"
            if prior_snap is not None:
                self._write_error_record_locked(
                    task_id, msg, mode="restore", prior=prior_snap
                )
            else:
                self._write_error_record_locked(task_id, msg, mode="upsert")
            raise RuntimeError(
                f"partial delete failure: native registration removed "
                f"but APS job delete {outcome} for {task_id}"
            )

    async def _status_snapshot_locked(
        self, task_id: str, manager: SchedulerManager | None = None
    ) -> SystemTaskStatusResponse | None:
        state = self._load_state()
        if state.corrupt:
            raise RuntimeError(
                "system_tasks.json corrupt; status unavailable"
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
        status, _ = await self._authoritative_status_locked(
            state, reg, manager=manager
        )
        return status

    # ------------------------------------------------------------------
    # status / list
    # ------------------------------------------------------------------

    async def _authoritative_status_locked(
        self,
        state: _SystemTaskState,
        rec: SystemTaskOperationalRecord,
        *,
        manager: SchedulerManager | None,
    ) -> tuple[SystemTaskStatusResponse, ScheduledTask | None]:
        """Return (status, APS task). Task is read once for reuse by callers."""
        if state.corrupt:
            raise RuntimeError("system_tasks.json corrupt; status unavailable")

        task: ScheduledTask | None = None
        aps_missing = False
        aps_error: str | None = None
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

        if task is not None and not task.wakeup_enabled:
            return (
                self._status_from_record(
                    rec,
                    rec.task_id,
                    task=task,
                    path_valid=False,
                    os_registered=False,
                    verified=False,
                    reason="APS wakeup_enabled is false",
                ),
                task,
            )

        os_registered = False
        verified = False
        detail = aps_error or ""
        if task is None:
            detail = aps_error or (
                "APS job missing" if aps_missing else "APS schedule unknown"
            )
            presence = await self._query_presence(rec.task_id)
            if presence == "unknown":
                detail = f"{detail}; native query error (unknown)"
            elif presence == "present":
                detail = f"{detail}; historical native may still be present"
        else:
            presence = await self._query_presence(rec.task_id)
            if presence == "unknown":
                detail = "native query error (unknown)"
            elif presence == "present":
                os_registered = True
                try:
                    exe, args = self.build_command_for_task(rec.task_id)
                    spec = SystemTaskSpec(
                        task_id=rec.task_id,
                        task_name=task.name,
                        exe_path=exe,
                        cli_args=list(args),
                        trigger=map_trigger_to_os_spec(task.trigger_config),
                        working_dir=str(self._app_root_dir),
                    )
                    ok, vdetail = await self.backend.verify_registration(spec)
                    verified = ok
                    detail = vdetail if not ok else "verified"
                except Exception as e:
                    detail = f"verify error: {e}"
                    verified = False
            else:
                detail = "native absent"

        path_valid = False
        if (
            task is not None
            and task.wakeup_enabled
            and os_registered
            and verified
            and rec.registered_exe_path
        ):
            exe, _ = self.build_command_for_task(rec.task_id)
            path_valid = rec.registered_exe_path == exe

        return (
            self._status_from_record(
                rec,
                rec.task_id,
                task=task,
                path_valid=path_valid,
                os_registered=os_registered,
                verified=verified,
                reason=detail,
            ),
            task,
        )

    async def get_status(
        self, task_id: str, manager: SchedulerManager | None = None
    ) -> SystemTaskStatusResponse:
        async with self._async_lock:
            state = self._load_state()
            if state.corrupt:
                raise RuntimeError("system_tasks.json corrupt; status unavailable")
            reg = self._find_record(state, task_id)
            if not reg:
                return SystemTaskStatusResponse(
                    task_id=task_id,
                    registered=False,
                    path_valid=False,
                    reason="no operational record",
                    verified=False,
                )
            status, _ = await self._authoritative_status_locked(
                state, reg, manager=manager
            )
            return status

    async def list_registered(
        self, manager: SchedulerManager | None = None
    ) -> list[SystemTaskRegistration]:
        async with self._async_lock:
            state = self._load_state()
            if state.corrupt:
                raise RuntimeError("system_tasks.json corrupt; list unavailable")
            out: list[SystemTaskRegistration] = []
            for rec in state.records:
                status, task = await self._authoritative_status_locked(
                    state, rec, manager=manager
                )
                out.append(
                    self._hydrate_registration(
                        rec,
                        task=task,
                        registered=status.registered,
                        verified=bool(status.verified),
                        path_valid=status.path_valid,
                        reason=status.reason,
                        enabled=status.enabled,
                    )
                )
            return out

    # ------------------------------------------------------------------
    # reconciler
    # ------------------------------------------------------------------

    async def reconcile_task(
        self,
        manager: SchedulerManager,
        task_id: str,
    ) -> ReconcileTaskResult:
        async with self._async_lock:
            return await self._reconcile_task_locked(manager, task_id)

    async def reconcile_all(self, manager: SchedulerManager | None = None) -> dict:
        if manager is None:
            raise ValueError("reconcile_all requires SchedulerManager")
        async with self._async_lock:
            return await self._reconcile_all_locked(manager)

    async def repair_all(self, manager: SchedulerManager | None = None) -> dict:
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
                if kwargs.get("wakeup_enabled") is True:
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
            aps_decode_error: str | None = None
        except SchedulerJobDecodeError as e:
            task = None
            aps_decode_error = str(e)

        if aps_decode_error is not None:
            msg = f"APS job decode failed: {aps_decode_error}"
            if reg is not None:
                self._write_error_record_locked(task_id, msg, mode="existing_only")
            else:
                self._write_error_record_locked(task_id, msg, mode="upsert")
            return ReconcileTaskResult(
                task_id=task_id, action="error", detail=msg, native_error=msg
            )

        if task is None:
            if reg is None:
                try:
                    ok, err = await self._ensure_absent(task_id)
                    if not ok:
                        return ReconcileTaskResult(
                            task_id=task_id,
                            action="error",
                            detail=str(err),
                            native_error=str(err),
                        )
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
            return await self._reconcile_cleanup_locked(task_id, reg)

        if not task.wakeup_enabled:
            return await self._reconcile_cleanup_locked(task_id, reg)

        return await self._reconcile_ensure_native_locked(manager, task, reg)

    async def _reconcile_cleanup_locked(
        self, task_id: str, reg: SystemTaskOperationalRecord | None
    ) -> ReconcileTaskResult:
        ok, err = await self._ensure_absent(task_id)
        if not ok:
            if reg is not None:
                self._write_error_record_locked(
                    task_id, f"cleanup incomplete: {err}", mode="existing_only"
                )
            return ReconcileTaskResult(
                task_id=task_id,
                action="error",
                detail=f"cleanup incomplete: {err}",
                native_error=err,
            )
        if self._remove_operational_record_locked(task_id):
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
        reg: SystemTaskOperationalRecord | None,
    ) -> ReconcileTaskResult:
        assert task.wakeup_enabled
        task_id = task.id
        try:
            aps_os_trigger = map_trigger_to_os_spec(task.trigger_config)
        except Exception as e:
            msg = f"APS trigger map failed: {e}"
            if reg is not None:
                self._write_error_record_locked(task_id, msg, mode="existing_only")
            else:
                self._write_error_record_locked(task_id, msg, mode="upsert")
            return ReconcileTaskResult(
                task_id=task_id, action="error", detail=msg, native_error=msg
            )

        warnings = list(
            validate_trigger_for_platform(self.backend.platform_name, aps_os_trigger)
        )
        del warnings  # not persisted on simplified operational record
        current_exe, current_args = self.build_command_for_task(task_id)
        working_dir = str(self._app_root_dir)

        presence = await self._query_presence(task_id)
        if presence == "unknown":
            msg = "native query error (unknown)"
            if reg is not None:
                self._write_error_record_locked(task_id, msg, mode="existing_only")
            else:
                self._write_error_record_locked(task_id, msg, mode="upsert")
            return ReconcileTaskResult(
                task_id=task_id, action="error", detail=msg, native_error=msg
            )

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
        elif reg.state == "error":
            need = True
            reason = "operational state is error"
        else:
            try:
                spec_check = SystemTaskSpec(
                    task_id=task_id,
                    task_name=task.name,
                    exe_path=current_exe,
                    cli_args=list(current_args),
                    trigger=aps_os_trigger,
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
            )
            state.records.append(r)
        self._save_state(state)

        spec = SystemTaskSpec(
            task_id=task_id,
            task_name=task.name,
            exe_path=current_exe,
            cli_args=list(current_args),
            trigger=aps_os_trigger,
            working_dir=working_dir,
        )
        try:
            await self.backend.register(spec)
            ok, detail = await self.backend.verify_registration(spec)
        except Exception as e:
            ok, detail = False, str(e)

        if not ok:
            try:
                await self.backend.unregister(task_id)
            except Exception as ce:
                detail = f"{detail}; compensation unregister failed: {ce}"
            still = await self._query_presence(task_id)
            detail = f"{detail}; still_present={still}"
            self._write_error_record_locked(task_id, detail, mode="existing_only")
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
        r.registered_exe_path = current_exe
        r.last_registered_at = datetime.now()
        r.last_error = None
        self._save_state(state)
        if materialized:
            action = "materialized"
        elif presence == "absent":
            action = "registered"
        else:
            action = "updated"
        return ReconcileTaskResult(task_id=task_id, action=action, detail=reason)
