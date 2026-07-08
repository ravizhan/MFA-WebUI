export type RealtimeEventName =
  | "log"
  | "focus.display"
  | "task.started"
  | "task.completed"
  | "task.failed"
  | "notification.test"
  | "resource.loading"
  | "controller.action"
  | "tasker.task"
  | "node.recognition"
  | "node.action"
  | "sink"

export type RealtimeEventLevel = "info" | "success" | "error"

export interface RealtimeEvent {
  event: RealtimeEventName
  level: RealtimeEventLevel
  message: string
  time: string
  notify: string[]
  title?: string | null
  details?: Record<string, unknown> | null
  display: boolean
}
