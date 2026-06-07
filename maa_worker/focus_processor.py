"""
Focus 事件处理器 — 按 display_channels 将 FocusDisplayEvent 分发到对应通道。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from maa_worker.focus_protocol import (
    DISPLAY_LOG,
    DISPLAY_NOTIFICATION,
    DISPLAY_TOAST,
    FocusDisplayEvent,
)

if TYPE_CHECKING:
    from maa_worker.event_service import EventService


class FocusEventProcessor:
    """将 FocusDisplayEvent 按 display_channels 分发。

    - "log":          SSE 日志推送
    - "toast":        SSE toast 推送（前端 Naive UI 渲染）
    - "notification": 系统通知 (plyer / browser Notification)
    """

    def __init__(self, events: "EventService") -> None:
        self._events = events

    def dispatch(self, event: FocusDisplayEvent) -> None:
        content = event.content
        level = event.level

        if event.has_log:
            self._events.emit(
                "focus.display",
                content,
                level=level,
                display=[DISPLAY_LOG],
            )

        if event.has_toast:
            self._events.emit(
                "focus.display",
                content,
                level=level,
                display=[DISPLAY_TOAST],
            )

        if event.has_notification:
            self._events.send_notification(
                "任务通知",
                content,
                event="focus.display",
                level=level,
            )
