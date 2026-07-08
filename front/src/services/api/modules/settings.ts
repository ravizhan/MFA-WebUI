import type { SettingsModel } from "@/types/settingsModel"
import { showGlobalMessage } from "@/services/feedback/message"
import type { ApiResponse } from "@/services/api/core/types"
import i18n from "@/app/i18n"

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
  const t = i18n.global.t
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
        showGlobalMessage("success", t("settings.saveSuccess"))
        return true
      }
      showGlobalMessage("error", data.message || t("settings.saveFailed"))
      return false
    })
    .catch((error) => {
      console.error("Failed to update settings:", error)
      showGlobalMessage("error", t("settings.networkError"))
      return false
    })
}
