import type { ManualStartPayload, ManualStartResult, StartConflict } from "@/types/schedulerModel"
import { showGlobalMessage } from "@/services/feedback/message"
import { tryCatch } from "@/utils/tryCatch"

interface StartTaskApiResponse {
  status: string
  message?: string
  run_id?: string
  conflict?: StartConflict
}

function parseStartTaskResult(data: StartTaskApiResponse): ManualStartResult {
  if (data.status === "success") {
    return { accepted: true, runId: data.run_id ?? "" }
  }
  if (data.status === "conflict" && data.conflict) {
    return { accepted: false, conflict: data.conflict }
  }
  const message = data.message || "任务启动失败"
  showGlobalMessage("error", message)
  return { accepted: false, error: message }
}

export async function startTask(payload: ManualStartPayload): Promise<ManualStartResult> {
  const [data, error] = await tryCatch(async (): Promise<StartTaskApiResponse> => {
    const res = await fetch("/api/start", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: {
        "Content-Type": "application/json",
      },
    })
    return res.json()
  })
  if (error) {
    console.error("Failed to start task:", error)
    showGlobalMessage("error", "任务启动失败")
    return { accepted: false, error: "任务启动失败" }
  }
  return parseStartTaskResult(data)
}

export function stopTask(): Promise<boolean> {
  return fetch("/api/stop", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: { status: string; message?: string }) => {
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
