/**
 * Focused contract tests for CreatableSelect desired behavior.
 * Uses Vue createApp (no @vue/test-utils dependency).
 */
import { describe, expect, it, vi, afterEach } from "vitest"
import { createApp, nextTick, defineComponent, h, ref } from "vue"
import CreatableSelect from "@/components/common/CreatableSelect.vue"

vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    t: (key: string, params?: { value?: string }) =>
      params?.value ? `${key}:${params.value}` : key,
  }),
}))

const options = [
  { label: "Phone(127.0.0.1:5555)", value: "adb|/usr/bin/adb|127.0.0.1:5555" },
  { label: "192.168.1.10:5555", value: "adb||192.168.1.10:5555" },
]

function mountCreatable(props: {
  modelValue?: string | null
  options?: Array<{ label: string; value: string; disabled?: boolean }>
  onUpdate?: (v: string | null) => void
  onCreate?: (v: string) => void
  onOpen?: () => void
}) {
  const host = document.createElement("div")
  document.body.appendChild(host)

  const model = ref<string | null>(props.modelValue ?? null)
  const Root = defineComponent({
    setup() {
      return () =>
        h(CreatableSelect, {
          options: props.options ?? options,
          modelValue: model.value,
          "onUpdate:modelValue": (v: string | null) => {
            model.value = v
            props.onUpdate?.(v)
          },
          onCreate: (v: string) => {
            props.onCreate?.(v)
          },
          onOpen: () => {
            props.onOpen?.()
          },
        })
    },
  })

  const app = createApp(Root)
  app.mount(host)

  return {
    host,
    model,
    unmount() {
      app.unmount()
      host.remove()
    },
    input() {
      const el = host.querySelector("input")
      if (!el) {
        throw new Error("input not found")
      }
      return el
    },
  }
}

describe("CreatableSelect contract", () => {
  afterEach(() => {
    document.body.innerHTML = ""
    vi.useRealTimers()
  })

  it("emits open once per open session", async () => {
    const onOpen = vi.fn<() => void>()
    const m = mountCreatable({ onOpen })
    const input = m.input()

    input.dispatchEvent(new FocusEvent("focus"))
    await nextTick()
    expect(onOpen).toHaveBeenCalledTimes(1)

    input.dispatchEvent(new MouseEvent("click"))
    await nextTick()
    // Desired once-per-session: click while already open should not re-emit.
    expect(onOpen).toHaveBeenCalledTimes(1)

    m.unmount()
  })

  it("selecting an existing option emits update:modelValue only", async () => {
    const onUpdate = vi.fn<(v: string | null) => void>()
    const onCreate = vi.fn<(v: string) => void>()
    const m = mountCreatable({ onUpdate, onCreate })
    const input = m.input()

    input.dispatchEvent(new FocusEvent("focus"))
    await nextTick()

    const items = m.host.querySelectorAll("li[role='option']")
    expect(items.length).toBeGreaterThan(0)
    const first = items.item(0)
    if (!first) {
      throw new Error("option missing")
    }
    first.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }))
    await nextTick()

    expect(onUpdate).toHaveBeenCalledWith("adb|/usr/bin/adb|127.0.0.1:5555")
    expect(onCreate).not.toHaveBeenCalled()
    m.unmount()
  })

  it("selecting creatable option emits create only (no update:modelValue)", async () => {
    const onUpdate = vi.fn<(v: string | null) => void>()
    const onCreate = vi.fn<(v: string) => void>()
    const m = mountCreatable({ modelValue: null, onUpdate, onCreate })
    const input = m.input()

    input.dispatchEvent(new FocusEvent("focus"))
    await nextTick()

    const valueDesc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")
    valueDesc?.set?.call(input, "10.0.0.1:5555")
    input.dispatchEvent(new Event("input", { bubbles: true }))
    await nextTick()

    const createItem = Array.from(m.host.querySelectorAll("li[role='option']")).find((li) => {
      if (!(li instanceof HTMLElement)) {
        return false
      }
      return li.textContent?.includes("panel.useCustomValue") === true
    })
    expect(createItem).toBeTruthy()
    if (!(createItem instanceof HTMLElement)) {
      throw new Error("create option missing")
    }
    createItem.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }))
    await nextTick()

    expect(onCreate).toHaveBeenCalledWith("10.0.0.1:5555")
    expect(onUpdate).not.toHaveBeenCalled()
    m.unmount()
  })

  it("blur does not commit typed text", async () => {
    vi.useFakeTimers()
    const onUpdate = vi.fn<(v: string | null) => void>()
    const onCreate = vi.fn<(v: string) => void>()
    const m = mountCreatable({ modelValue: null, onUpdate, onCreate })
    const input = m.input()

    input.dispatchEvent(new FocusEvent("focus"))
    await nextTick()

    const valueDesc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")
    valueDesc?.set?.call(input, "half-typed")
    input.dispatchEvent(new Event("input", { bubbles: true }))
    await nextTick()

    input.dispatchEvent(new FocusEvent("blur"))
    vi.advanceTimersByTime(250)
    await nextTick()

    expect(onUpdate).not.toHaveBeenCalled()
    expect(onCreate).not.toHaveBeenCalled()
    expect(m.model.value).toBeNull()
    m.unmount()
  })
})
