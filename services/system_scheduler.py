"""
SystemScheduler: stateless OS native wakeup materialization + startup convergence.

No JSON state, no asyncio lock, no compensation state machine.
APS desired set (wakeup_enabled tasks) is the sole source of truth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from models.scheduler import CronTriggerConfig, ScheduledTask
from services.native_cron import parse_native_cron
from services.system_scheduler_backend import (
    NativeTaskSpec,
    SystemSchedulerBackend,
    build_native_command,
    get_backend,
)

logger = logging.getLogger(__name__)


@dataclass
class ConvergeReport:
    """Result of one converge() pass."""

    registered: list[str] = field(default_factory=list)
    unregistered: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


class SystemScheduler:
    """Stateless adapter: ScheduledTask → OS native registration."""

    def __init__(
        self,
        app_root: Path,
        backend: SystemSchedulerBackend | None = None,
    ) -> None:
        self._app_root = Path(app_root)
        self._backend = backend if backend is not None else get_backend()

    @property
    def backend(self) -> SystemSchedulerBackend:
        return self._backend

    def register(self, task: ScheduledTask) -> None:
        """Parse cron and register with OS (create-or-update). Raises ValueError / RuntimeError."""
        spec = self._build_spec(task)
        self._backend.register(spec)
        logger.info("native register ok: %s", task.id)

    def unregister(self, task_id: str) -> None:
        """Unregister OS native task. Propagates backend errors."""
        self._backend.unregister(task_id)
        logger.info("native unregister ok: %s", task_id)

    def converge(self, desired: list[ScheduledTask]) -> ConvergeReport:
        """Materialize desired set: register each desired, unregister observed orphans.

        Backend register is create-or-update. Exceptions are collected into
        report.failed so one bad task does not abort the rest of startup converge.
        """
        report = ConvergeReport()
        desired_by_id = {t.id: t for t in desired}
        desired_ids = set(desired_by_id.keys())

        try:
            observed = set(self._backend.list_registered_task_ids())
        except Exception as e:
            # Cannot list → cannot safely unregister orphans; still try register each.
            logger.warning("list_registered_task_ids failed: %s", e)
            observed = set()
            report.failed.append(("*", f"list_registered_task_ids: {e}"))

        for task_id, task in desired_by_id.items():
            try:
                self.register(task)
                report.registered.append(task_id)
            except Exception as e:
                logger.warning("converge register failed for %s: %s", task_id, e)
                report.failed.append((task_id, str(e)))

        for orphan_id in sorted(observed - desired_ids):
            try:
                self.unregister(orphan_id)
                report.unregistered.append(orphan_id)
            except Exception as e:
                logger.warning("converge unregister failed for %s: %s", orphan_id, e)
                report.failed.append((orphan_id, str(e)))

        logger.info(
            "converge done: registered=%s unregistered=%s failed=%s",
            len(report.registered),
            len(report.unregistered),
            len(report.failed),
        )
        return report

    def _build_spec(self, task: ScheduledTask) -> NativeTaskSpec:
        if not isinstance(task.trigger_config, CronTriggerConfig):
            raise ValueError(
                f"native wakeup 仅支持 cron 触发器，收到: "
                f"{type(task.trigger_config).__name__}"
            )
        cron = parse_native_cron(task.trigger_config.cron)
        exe_path, cli_args = build_native_command(self._app_root, task.id)
        return NativeTaskSpec(
            task_id=task.id,
            task_name=task.name,
            exe_path=exe_path,
            cli_args=list(cli_args),
            cron=cron,
            working_dir=str(self._app_root),
        )
