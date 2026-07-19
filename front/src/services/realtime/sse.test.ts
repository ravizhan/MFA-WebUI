import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// setup.ts provides a global EventSource mock used only as a boundary stub.
import { SSEClient } from "@/services/realtime/sse"

describe("SSEClient", () => {
  let mockEventSourceCtor: ReturnType<typeof vi.fn>

  function getESInstance(index = 0) {
    const instance = mockEventSourceCtor.mock.results[index]?.value
    if (!instance) {
      throw new Error(`No EventSource instance at index ${index}`)
    }
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    return instance as {
      close: ReturnType<typeof vi.fn>
      onopen: (() => void) | null
      onmessage: ((event: { data: string }) => void) | null
      onerror: ((event: unknown) => void) | null
    }
  }

  beforeEach(() => {
    vi.useFakeTimers()
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    mockEventSourceCtor = vi.mocked(globalThis.EventSource as unknown as ReturnType<typeof vi.fn>)
    mockEventSourceCtor.mockClear()
    // Suppress console output from sse.ts error/reconnect paths exercised below.
    vi.spyOn(console, "error").mockImplementation(() => {})
    vi.spyOn(console, "log").mockImplementation(() => {})
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe("connection lifecycle", () => {
    it("connects on construction and closes EventSource on close()", () => {
      const client = new SSEClient("/api/logs")
      expect(mockEventSourceCtor).toHaveBeenCalledWith("/api/logs")
      const instance = getESInstance()
      client.close()
      expect(instance.close).toHaveBeenCalled()
    })

    it("does not reconnect when manually closed", () => {
      const client = new SSEClient("/api/logs")
      client.close()

      const instance = getESInstance()
      instance.onerror?.(new Event("error"))

      vi.advanceTimersByTime(5000)

      expect(mockEventSourceCtor).toHaveBeenCalledTimes(1)
    })

    it("reconnect re-establishes connection", () => {
      const client = new SSEClient("/api/logs")
      client.close()

      mockEventSourceCtor.mockClear()

      client.reconnect()

      expect(mockEventSourceCtor).toHaveBeenCalledTimes(1)
      client.close()
    })

    it("close() after error clears pending reconnect timer", () => {
      const client = new SSEClient("/api/logs")

      const instance = getESInstance()
      instance.onerror?.(new Event("error"))

      client.close()
      vi.advanceTimersByTime(5000)

      expect(mockEventSourceCtor).toHaveBeenCalledTimes(1)
    })
  })

  describe("event dispatching and normalization", () => {
    it("dispatches normalized events to registered listeners", () => {
      const client = new SSEClient("/api/logs")
      const listener = vi.fn<() => void>()
      client.addEventListener("log", listener)

      const instance = getESInstance()
      instance.onmessage?.({
        data: JSON.stringify({
          event: "log",
          level: "info",
          message: "hello world",
          time: "2024-01-01T00:00:00Z",
          notify: [],
        }),
      })

      expect(listener).toHaveBeenCalledTimes(1)
      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          event: "log",
          level: "info",
          message: "hello world",
        }),
      )
      client.close()
    })

    it("ignores invalid JSON and messages without message field", () => {
      const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {})
      const client = new SSEClient("/api/logs")
      const listener = vi.fn<() => void>()
      client.addEventListener("log", listener)

      const instance = getESInstance()
      instance.onmessage?.({ data: "not valid json" })
      instance.onmessage?.({
        data: JSON.stringify({ event: "log" }),
      })

      expect(listener).not.toHaveBeenCalled()
      expect(consoleSpy).toHaveBeenCalledWith("SSE消息解析错误:", expect.any(SyntaxError))
      consoleSpy.mockRestore()
      client.close()
    })

    it("adds and removes event listeners", () => {
      const client = new SSEClient("/api/logs")
      const listener = vi.fn<() => void>()
      client.addEventListener("task.started", listener)
      client.removeEventListener("task.started", listener)

      const instance = getESInstance()
      instance.onmessage?.({
        data: JSON.stringify({
          event: "task.started",
          level: "info",
          message: "task running",
          time: "",
          notify: [],
        }),
      })

      expect(listener).not.toHaveBeenCalled()
      client.close()
    })

    it("normalizes legacy type, defaults, display, title, and details", () => {
      const client = new SSEClient("/api/logs")
      const legacyListener = vi.fn<() => void>()
      const defaultsListener = vi.fn<() => void>()
      client.addEventListener("custom", legacyListener)
      client.addEventListener("log", defaultsListener)

      const instance = getESInstance()
      instance.onmessage?.({
        data: JSON.stringify({
          type: "custom",
          level: "success",
          message: "legacy format",
          time: "2024-01-01T00:00:00Z",
        }),
      })
      expect(legacyListener).toHaveBeenCalledWith(
        expect.objectContaining({
          event: "custom",
          level: "success",
          message: "legacy format",
        }),
      )

      instance.onmessage?.({
        data: JSON.stringify({
          message: "bare message",
          display: false,
          title: "Notification Title",
          details: { key: "value", count: 42 },
        }),
      })
      expect(defaultsListener).toHaveBeenCalledWith(
        expect.objectContaining({
          event: "log",
          level: "info",
          message: "bare message",
          time: "",
          notify: [],
          display: false,
          title: "Notification Title",
          details: { key: "value", count: 42 },
        }),
      )

      instance.onmessage?.({
        data: JSON.stringify({
          level: "info",
          message: "no extras",
        }),
      })
      expect(defaultsListener).toHaveBeenCalledWith(
        expect.objectContaining({
          title: null,
          details: null,
          display: true,
        }),
      )
      client.close()
    })
  })

  describe("reconnect behavior", () => {
    it("schedules reconnect on error with exponential backoff and onopen reset", () => {
      vi.spyOn(Math, "random").mockReturnValue(0)

      const client = new SSEClient("/api/logs")

      // First error: baseDelay = 1000 * 2^0 = 1000
      const instance1 = getESInstance(0)
      instance1.onerror?.(new Event("error"))

      vi.advanceTimersByTime(500)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(1)

      vi.advanceTimersByTime(500)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(2)

      // Second error: baseDelay = 1000 * 2^1 = 2000
      const instance2 = getESInstance(1)
      instance2.onerror?.(new Event("error"))

      vi.advanceTimersByTime(1000)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(2)

      vi.advanceTimersByTime(2000)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(3)

      // Successful open resets attempts to base delay
      const instance3 = getESInstance(2)
      instance3.onopen?.()
      instance3.onerror?.(new Event("error"))

      vi.advanceTimersByTime(500)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(3)

      vi.advanceTimersByTime(500)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(4)

      vi.spyOn(Math, "random").mockRestore()
      client.close()
    })
  })
})
