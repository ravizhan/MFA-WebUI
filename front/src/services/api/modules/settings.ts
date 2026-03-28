import type { SettingsModel } from "@/types/settings/model"
import { showGlobalMessage } from "@/services/feedback/message"
import type { ApiResponse } from "@/services/api/core/types"

interface SettingsResponse {
  status: string
  settings: SettingsModel
}

export function getSettings(): Promise<SettingsModel> {
  return fetch("/api/settings", { method: "GET" })
    .then((res) => res.json())
    .then((data: SettingsResponse) => data.settings)
}

export function updateSettings(settings: SettingsModel): Promise<boolean> {
  return fetch("/api/settings", {
    method: "POST",
    body: JSON.stringify(settings),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        showGlobalMessage("success", "设置已保存")
        return true
      }
      showGlobalMessage("error", data.message || "保存失败")
      return false
    })
    .catch((error) => {
      console.error("Failed to update settings:", error)
      showGlobalMessage("error", "网络错误，请稍后重试")
      return false
    })
}
