import type { MessageApiInjection } from "naive-ui/es/message/src/MessageProvider"

export type GlobalMessageType = "info" | "success" | "warning" | "error"

interface QueuedMessage {
  type: GlobalMessageType
  content: string
}

let messageApi: MessageApiInjection | null = null
let queue: QueuedMessage[] = []

/**
 * Registers the naive-ui message API. Called once by FeedbackBridge after mount.
 * Any messages queued before registration are flushed immediately.
 */
export function registerMessageApi(api: MessageApiInjection): void {
  messageApi = api
  const pending = queue
  queue = []
  for (const { type, content } of pending) {
    messageApi.create(content, { type, duration: 3000 })
  }
}

export function showGlobalMessage(type: GlobalMessageType, content: string): void {
  if (messageApi) {
    messageApi.create(content, { type, duration: 3000 })
    return
  }
  queue.push({ type, content })
}

/** Test-only: resets the bridge so unit tests start from a clean slate. */
export function _resetMessageApiForTest(): void {
  messageApi = null
  queue = []
}
