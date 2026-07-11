import { ref } from "vue"

export type GlobalMessageType = "info" | "success" | "warning" | "error"

interface ToastItem {
  id: number
  type: GlobalMessageType
  content: string
}

const toasts = ref<ToastItem[]>([])
let toastId = 0

export function showGlobalMessage(type: GlobalMessageType, content: string): void {
  const id = ++toastId
  toasts.value.push({ id, type, content })
  setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }, 3000)
}

export function useToasts() {
  return toasts
}
