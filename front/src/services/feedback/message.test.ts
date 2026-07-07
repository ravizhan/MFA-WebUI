import { describe, expect, it, beforeEach, vi } from "vitest"

let showGlobalMessage: (type: "info" | "success" | "warning" | "error", content: string) => void
let useToasts: () => { value: { id: number; type: string; content: string }[] }

describe("message service", () => {
  beforeEach(async () => {
    vi.resetModules()
    const messageModule = await import("@/services/feedback/message")
    showGlobalMessage = messageModule.showGlobalMessage
    useToasts = messageModule.useToasts as () => {
      value: { id: number; type: string; content: string }[]
    }
  })

  describe("showGlobalMessage", () => {
    it("adds a toast with correct type and content", () => {
      showGlobalMessage("success", "operation completed")
      const toasts = useToasts()
      expect(toasts.value).toHaveLength(1)
      expect(toasts.value[0].type).toBe("success")
      expect(toasts.value[0].content).toBe("operation completed")
    })

    it("auto-removes toast after 3 seconds", () => {
      vi.useFakeTimers()
      showGlobalMessage("info", "temporary message")
      expect(useToasts().value).toHaveLength(1)

      vi.advanceTimersByTime(3000)
      expect(useToasts().value).toHaveLength(0)
      vi.useRealTimers()
    })
  })

  describe("useToasts", () => {
    it("returns the reactive toasts ref", () => {
      const toasts = useToasts()
      showGlobalMessage("error", "error message")
      expect(toasts.value).toHaveLength(1)
      expect(toasts.value[0].type).toBe("error")
    })
  })
})
