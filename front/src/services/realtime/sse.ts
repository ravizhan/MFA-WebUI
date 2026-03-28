import type { RealtimeEvent, RealtimeEventLevel, RealtimeEventName } from "@/types/realtime/model"

type SSEPayload =
  | RealtimeEvent
  | { type?: string; message?: string; time?: string; notify?: boolean }

export class SSEClient {
  private eventSource: EventSource | null = null
  private url: string
  private listeners: Map<string, Set<(data: RealtimeEvent) => void>> = new Map()
  private baseReconnectInterval: number = 1000
  private maxReconnectInterval: number = 30000
  private reconnectAttempts: number = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private isManuallyClosed: boolean = false

  constructor(url: string) {
    this.url = url
    this.connect()
  }

  private connect(): void {
    if (this.isManuallyClosed) return

    this.clearReconnectTimer()
    this.eventSource?.close()
    this.eventSource = new EventSource(this.url)

    this.eventSource.onmessage = (event) => {
      try {
        const data = this.normalizeEvent(JSON.parse(event.data) as SSEPayload)
        if (!data) {
          return
        }
        this.dispatchEvent(data.event, data)
      } catch (error) {
        console.error("SSE消息解析错误:", error)
      }
    }

    this.eventSource.onopen = () => {
      console.log("SSE连接成功")
      this.reconnectAttempts = 0
    }

    this.eventSource.onerror = (error) => {
      console.error("SSE连接错误:", error)
      this.eventSource?.close()
      this.eventSource = null
      this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    if (this.isManuallyClosed || this.reconnectTimer) return

    const exponentialDelay = Math.min(
      this.maxReconnectInterval,
      this.baseReconnectInterval * 2 ** this.reconnectAttempts,
    )
    const jitter = Math.floor(Math.random() * 500)
    const delay = exponentialDelay + jitter

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.reconnectAttempts++
      console.log(`SSE重连尝试 #${this.reconnectAttempts}，等待 ${delay}ms`)
      this.connect()
    }, delay)
  }

  private clearReconnectTimer(): void {
    if (!this.reconnectTimer) return
    clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
  }

  public addEventListener(type: string, callback: (data: RealtimeEvent) => void): void {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set())
    }
    this.listeners.get(type)?.add(callback)
  }

  public removeEventListener(type: string, callback: (data: RealtimeEvent) => void): void {
    this.listeners.get(type)?.delete(callback)
  }

  private normalizeEvent(data: SSEPayload): RealtimeEvent | null {
    if (!data || typeof data.message !== "string") {
      return null
    }

    const eventType = ("event" in data ? data.event : data.type) ?? "log"
    const level = ("level" in data ? data.level : undefined) ?? "info"

    return {
      event: (eventType as RealtimeEventName) || "log",
      level: (level as RealtimeEventLevel) || "info",
      message: data.message,
      time: ("time" in data && typeof data.time === "string" ? data.time : "") || "",
      notify: ("notify" in data && typeof data.notify === "boolean" ? data.notify : false) || false,
      title: "title" in data && typeof data.title === "string" ? data.title : null,
    }
  }

  private dispatchEvent(type: string, data: RealtimeEvent): void {
    this.listeners.get(type)?.forEach((callback) => callback(data))
  }

  public close(): void {
    this.isManuallyClosed = true
    this.clearReconnectTimer()
    this.eventSource?.close()
    this.eventSource = null
  }

  public reconnect(): void {
    this.isManuallyClosed = false
    this.reconnectAttempts = 0
    this.connect()
  }
}

export const sse = new SSEClient("/api/logs")
