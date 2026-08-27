import { describe, expect, it, beforeEach, vi } from "vitest"
import type { MessageApiInjection } from "naive-ui/es/message/src/MessageProvider"

let showGlobalMessage: (type: "info" | "success" | "warning" | "error", content: string) => void
let registerMessageApi: (api: MessageApiInjection) => void
let _resetMessageApiForTest: () => void

function makeApiSpy(): MessageApiInjection {
  return {
    create: vi.fn<MessageApiInjection["create"]>(),
    info: vi.fn<MessageApiInjection["info"]>(),
    success: vi.fn<MessageApiInjection["success"]>(),
    warning: vi.fn<MessageApiInjection["warning"]>(),
    error: vi.fn<MessageApiInjection["error"]>(),
    loading: vi.fn<MessageApiInjection["loading"]>(),
    destroyAll: vi.fn<MessageApiInjection["destroyAll"]>(),
  }
}

describe("message service", () => {
  beforeEach(async () => {
    vi.resetModules()
    const messageModule = await import("@/services/feedback/message")
    showGlobalMessage = messageModule.showGlobalMessage
    registerMessageApi = messageModule.registerMessageApi
    _resetMessageApiForTest = messageModule._resetMessageApiForTest
    _resetMessageApiForTest()
  })

  it("delegates to the registered naive message api", () => {
    const api = makeApiSpy()
    registerMessageApi(api)
    showGlobalMessage("success", "operation completed")
    expect(api.create).toHaveBeenCalledWith("operation completed", {
      type: "success",
      duration: 3000,
    })
  })

  it("passes the message type through", () => {
    const api = makeApiSpy()
    registerMessageApi(api)
    showGlobalMessage("error", "failure")
    expect(api.create).toHaveBeenCalledWith("failure", { type: "error", duration: 3000 })
  })

  it("auto-dismisses after 3 seconds via duration option", () => {
    const api = makeApiSpy()
    registerMessageApi(api)
    showGlobalMessage("info", "temporary message")
    expect(api.create).toHaveBeenCalledWith("temporary message", {
      type: "info",
      duration: 3000,
    })
  })

  it("queues messages before registration and flushes them on register", () => {
    showGlobalMessage("warning", "queued before mount")
    const api = makeApiSpy()
    registerMessageApi(api)
    expect(api.create).toHaveBeenCalledWith("queued before mount", {
      type: "warning",
      duration: 3000,
    })
  })
})
