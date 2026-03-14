import type { ApiResponse } from "./shared"

export function testNotificationApi(): Promise<ApiResponse> {
  return fetch("/api/test-notification", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}
