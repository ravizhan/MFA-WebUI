"""
Focus 事件处理器 — 按 display_channels 将 FocusDisplayEvent 分发到对应通道。
"""

from typing import TYPE_CHECKING

from maa_worker.focus_protocol import (
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
        notify: list[str] = []
        if event.has_toast:
            notify.append(DISPLAY_TOAST)
        if event.has_notification:
            notify.append(DISPLAY_NOTIFICATION)

        self._events.emit(
            "focus.display",
            event.content,
            display=event.has_log,
            notify=notify,
            level=event.level,
        )
