export type RealtimeEventName =
  | "log"
  | "task.started"
  | "task.completed"
  | "task.failed"
  | "notification.test"

export type RealtimeEventLevel = "info" | "success" | "error"

export interface RealtimeEvent {
  event: RealtimeEventName
  level: RealtimeEventLevel
  message: string
  time: string
  notify: boolean
  title?: string | null
}
