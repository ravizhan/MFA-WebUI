import { beforeEach, describe, expect, it } from "vitest"
import { createPinia, setActivePinia } from "pinia"

import { useInterfaceStore } from "@/stores/interface/interface"
import type { Pretask } from "@/types/interfaceModel"

const matchingPretask: Pretask = {
  exec: "prepare.exe",
  controller: ["adb"],
  resource: ["resource-a"],
}

const controllerMismatchPretask: Pretask = {
  exec: "prepare.exe",
  controller: ["other-controller"],
  resource: ["resource-a"],
}

const resourceMismatchPretask: Pretask = {
  exec: "prepare.exe",
  controller: ["adb"],
  resource: ["other-resource"],
}

const undefinedContextPretask: Pretask = {
  exec: "prepare.exe",
  controller: ["adb"],
  resource: ["resource-a"],
}

describe("useInterfaceStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe("isPretaskCompatible", () => {
    it("returns true when controller and resource match", () => {
      const store = useInterfaceStore()

      expect(store.isPretaskCompatible(matchingPretask, "adb", "resource-a")).toBe(true)
    })

    it("returns false when the controller does not match", () => {
      const store = useInterfaceStore()

      expect(store.isPretaskCompatible(controllerMismatchPretask, "adb", "resource-a")).toBe(false)
    })

    it("returns false when the resource does not match", () => {
      const store = useInterfaceStore()

      expect(store.isPretaskCompatible(resourceMismatchPretask, "adb", "resource-a")).toBe(false)
    })

    it("returns true when the context is undefined", () => {
      const store = useInterfaceStore()

      expect(store.isPretaskCompatible(undefinedContextPretask, undefined, undefined)).toBe(true)
    })
  })
})
