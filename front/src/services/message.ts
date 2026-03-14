import type { MessageApiInjection } from "naive-ui"

declare global {
  interface Window {
    $message?: MessageApiInjection
  }
}

export type GlobalMessageType = "info" | "success" | "warning" | "error"

export function showGlobalMessage(type: GlobalMessageType, content: string): void {
  if (typeof window === "undefined") {
    return
  }
  window.$message?.[type](content)
}
