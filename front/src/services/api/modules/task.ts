import type { TaskExecutionPayload } from "@/types/schedulerModel"
import { showGlobalMessage } from "@/services/feedback/message"
import type { ApiResponse } from "@/services/api/core/types"

export function startTask(payload: TaskExecutionPayload): Promise<boolean> {
  return fetch("/api/start", {
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
        return false
      }
      return true
    })
    .catch((error) => {
      console.error("Failed to start task:", error)
      showGlobalMessage("error", "任务启动失败")
      return false
    })
}

export function stopTask(): Promise<boolean> {
  return fetch("/api/stop", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        showGlobalMessage("success", "正在中止任务，请稍后")
        return true
      }
      showGlobalMessage("error", data.message || "任务停止失败")
      return false
    })
    .catch((error) => {
      console.error("Failed to stop task:", error)
      showGlobalMessage("error", "任务停止失败")
      return false
    })
}
