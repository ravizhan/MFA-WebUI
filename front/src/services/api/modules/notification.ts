import type { ApiResponse } from "@/services/api/core/types"

export function testNotificationApi(): Promise<ApiResponse> {
  return fetch("/api/test-notification", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}
