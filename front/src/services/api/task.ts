import type { TaskExecutionPayload } from "../../types/scheduler"
import { showGlobalMessage } from "../message"
import type { ApiResponse } from "./shared"

export function startTask(payload: TaskExecutionPayload): void {
  fetch("/api/start", {
    method: "POST",
    body: JSON.stringify(payload),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status !== "success") {
        showGlobalMessage("error", data.message || "任务启动失败")
      }
    })
}

export function stopTask(): void {
  fetch("/api/stop", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        showGlobalMessage("success", "正在中止任务，请稍后")
      } else {
        showGlobalMessage("error", data.message || "任务停止失败")
      }
    })
}
