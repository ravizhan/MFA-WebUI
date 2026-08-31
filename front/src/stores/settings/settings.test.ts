import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/services/api", () => ({
  getSettings: vi.fn<() => void>(),
  updateSettings: vi.fn<() => void>(),
}))

import * as api from "@/services/api"
import { useSettingsStore } from "@/stores/settings/settings"

function deferred<T>() {
  let resolvePromise: (value: T) => void = () => undefined
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve
  })
  return { promise, resolve: resolvePromise }
}

describe("settings persistence", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it("serializes rapid whole-document writes without losing either field", async () => {
    const first = deferred<boolean>()
    const second = deferred<boolean>()
    vi.mocked(api.updateSettings)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)

    const store = useSettingsStore()
    const firstUpdate = store.updateSetting("runtime", "timeout", 120)
    const secondUpdate = store.updateSetting("runtime", "retryInterval", 10)

    await vi.waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1))
    first.resolve(true)
    await vi.waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(2))

    expect(vi.mocked(api.updateSettings).mock.calls[1][0].runtime).toMatchObject({
      timeout: 120,
      retryInterval: 10,
    })

    second.resolve(true)
    await expect(Promise.all([firstUpdate, secondUpdate])).resolves.toEqual([true, true])
    expect(store.settings.runtime).toMatchObject({ timeout: 120, retryInterval: 10 })
  })

  it("does not let an older failed write roll back a newer value", async () => {
    const first = deferred<boolean>()
    const second = deferred<boolean>()
    vi.mocked(api.updateSettings)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)

    const store = useSettingsStore()
    const firstUpdate = store.updateSetting("runtime", "timeout", 120)
    const secondUpdate = store.updateSetting("runtime", "timeout", 180)

    await vi.waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1))
    first.resolve(false)
    await vi.waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(2))

    expect(store.settings.runtime.timeout).toBe(180)
    expect(vi.mocked(api.updateSettings).mock.calls[1][0].runtime.timeout).toBe(180)

    second.resolve(true)
    await expect(Promise.all([firstUpdate, secondUpdate])).resolves.toEqual([false, true])
    expect(store.settings.runtime.timeout).toBe(180)
  })
})
