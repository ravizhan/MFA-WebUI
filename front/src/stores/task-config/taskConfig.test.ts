import { describe, expect, it, beforeEach, afterEach, vi } from "vitest"
import { setActivePinia, createPinia } from "pinia"

vi.mock("@/services/api", () => ({
  getTaskConfig: vi.fn<() => void>(),
  saveTaskConfig: vi.fn<() => void>(),
  resetTaskConfig: vi.fn<() => void>(),
}))

import { useTaskConfigStore } from "@/stores/task-config/taskConfig"
import { useInterfaceStore } from "@/stores/interface/interface"
import * as api from "@/services/api"
import { CUSTOM_PRESET_NAME } from "@/types/taskConfigModel"
import type { InterfaceModel } from "@/types/interfaceModel"

function buildTestInterface(): InterfaceModel {
  return {
    interface_version: 2,
    name: "test-interface",
    controller: [],
    resource: [],
    task: [
      {
        name: "Task A",
        entry: "task-a",
        option: ["difficulty", "params"],
      },
      {
        name: "Task B",
        entry: "task-b",
        option: ["mode"],
      },
      {
        name: "Task C",
        entry: "task-c",
        option: [],
      },
    ],
    option: {
      difficulty: {
        type: "select",
        cases: [{ name: "easy" }, { name: "normal" }, { name: "hard" }],
        default_case: "normal",
      },
      params: {
        type: "input",
        inputs: [
          { name: "host", default: "localhost" },
          { name: "port", default: "" },
        ],
      },
      mode: {
        type: "checkbox",
        cases: [{ name: "auto" }, { name: "manual" }],
        default_case: ["auto"],
      },
    },
    preset: [
      {
        name: "preset1",
        task: [
          {
            name: "Task A",
            enabled: true,
            option: { difficulty: "hard", params: { host: "preset-host" } },
          },
          { name: "Task B", enabled: false },
        ],
      },
      {
        name: "preset2",
        task: [{ name: "Task B", enabled: true, option: { mode: ["manual"] } }],
      },
    ],
  }
}

function setupInterface() {
  const interfaceStore = useInterfaceStore()
  interfaceStore.interface = buildTestInterface()
  return interfaceStore
}

function initTaskConfigStore() {
  const store = useTaskConfigStore()
  store.presetSnapshots = store.seedPresetSnapshots()
  store.hydrateSnapshot(store.presetSnapshots[CUSTOM_PRESET_NAME])
  return store
}

describe("useTaskConfigStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal("crypto", { randomUUID: vi.fn<() => string>(() => "mock-uuid") })
    vi.clearAllMocks()
    setupInterface()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("has correct initial state", () => {
    const store = useTaskConfigStore()
    expect(store.options).toEqual({})
    expect(store.taskList).toEqual([])
    expect(store.selectedPresetName).toBe(CUSTOM_PRESET_NAME)
    expect(store.presetSnapshots).toEqual({})
    expect(store.configLoaded).toBe(false)
    expect(store.saveTimer).toBeNull()
    expect(store.preTasks).toEqual([])
  })

  describe("buildDefaultTaskList", () => {
    it("returns tasks from interface with checked=false", () => {
      const store = useTaskConfigStore()
      const list = store.buildDefaultTaskList()
      expect(list).toHaveLength(3)
      expect(list.map((t) => ({ id: t.id, name: t.name, checked: t.checked }))).toEqual([
        { id: "task-a", name: "Task A", checked: false },
        { id: "task-b", name: "Task B", checked: false },
        { id: "task-c", name: "Task C", checked: false },
      ])
    })
  })

  describe("selectPreset", () => {
    it("selects a preset, hydrates its snapshot and returns true", () => {
      const store = initTaskConfigStore()
      const result = store.selectPreset("preset1")

      expect(result).toBe(true)
      expect(store.selectedPresetName).toBe("preset1")
      expect(store.taskList.map((t) => t.id)).toEqual(["task-a", "task-b", "task-c"])
      expect(store.taskList.find((t) => t.id === "task-a")?.checked).toBe(true)
      expect(store.taskList.find((t) => t.id === "task-b")?.checked).toBe(false)
      expect(store.taskList.find((t) => t.id === "task-c")?.checked).toBe(false)
      expect(store.options["task-a"]).toEqual({
        difficulty: "hard",
        params: { host: "preset-host", port: "" },
      })
    })

    it("returns false and leaves state unchanged for unknown presets", () => {
      const store = initTaskConfigStore()
      const previousState = store.serializeCurrentSnapshot()
      const result = store.selectPreset("nonexistent")

      expect(result).toBe(false)
      expect(store.selectedPresetName).toBe(CUSTOM_PRESET_NAME)
      expect(store.serializeCurrentSnapshot()).toEqual(previousState)
    })

    it("returns true without changes when selecting the already-active preset", () => {
      const store = initTaskConfigStore()
      const previousState = store.serializeCurrentSnapshot()
      const result = store.selectPreset(CUSTOM_PRESET_NAME)

      expect(result).toBe(true)
      expect(store.selectedPresetName).toBe(CUSTOM_PRESET_NAME)
      expect(store.serializeCurrentSnapshot()).toEqual(previousState)
    })

    it("syncs current state to the previous preset before switching to custom", () => {
      const store = initTaskConfigStore()
      store.selectPreset("preset1")

      store.taskList.find((t) => t.id === "task-b")!.checked = true
      store.options["task-a"] = { ...store.options["task-a"], difficulty: "easy" }
      store.preTasks.push({ id: "pt1", command: "echo preset1", enabled: true, timeout: 30 })

      store.selectPreset(CUSTOM_PRESET_NAME)

      const preset1Snapshot = store.presetSnapshots["preset1"]
      expect(preset1Snapshot.taskChecked["task-b"]).toBe(true)
      expect(preset1Snapshot.taskOptions["task-a"]).toMatchObject({ difficulty: "easy" })
      expect(preset1Snapshot.preTasks).toHaveLength(1)
      expect(preset1Snapshot.preTasks[0].command).toBe("echo preset1")
    })

    it("syncs current state before switching between two real presets", () => {
      const store = initTaskConfigStore()
      store.selectPreset("preset1")

      store.taskList.find((t) => t.id === "task-c")!.checked = true
      store.options["task-b"] = { ...store.options["task-b"], mode: ["auto", "manual"] }

      const result = store.selectPreset("preset2")

      expect(result).toBe(true)
      const preset1Snapshot = store.presetSnapshots["preset1"]
      expect(preset1Snapshot.taskChecked["task-c"]).toBe(true)
      expect(preset1Snapshot.taskOptions["task-b"]).toMatchObject({ mode: ["auto", "manual"] })

      expect(store.selectedPresetName).toBe("preset2")
      expect(store.taskList.map((t) => t.id)).toEqual(["task-b", "task-a", "task-c"])
      expect(store.taskList.find((t) => t.id === "task-b")?.checked).toBe(true)
      expect(store.options["task-b"]).toEqual({ mode: ["manual"] })
    })
  })

  describe("serializeCurrentSnapshot", () => {
    it("serializes task order, checked state, merged options and a copy of preTasks", () => {
      const store = initTaskConfigStore()
      store.taskList = [store.taskList[2], store.taskList[0], store.taskList[1]]
      store.taskList[0].checked = true
      store.taskList[1].checked = true
      store.options["task-a"] = { ...store.options["task-a"], difficulty: "hard" }
      store.preTasks = [{ id: "pt1", command: "echo hello", enabled: true, timeout: 30 }]

      const snapshot = store.serializeCurrentSnapshot()

      expect(snapshot.taskOrder).toEqual(["task-c", "task-a", "task-b"])
      expect(snapshot.taskChecked).toEqual({
        "task-c": true,
        "task-a": true,
        "task-b": false,
      })
      expect(snapshot.taskOptions["task-a"]).toEqual({
        difficulty: "hard",
        params: { host: "localhost", port: "" },
      })
      expect(snapshot.preTasks).toEqual(store.preTasks)
      expect(snapshot.preTasks).not.toBe(store.preTasks)
    })
  })

  describe("normalizeSnapshot", () => {
    it("returns a valid default snapshot when given undefined", () => {
      const store = initTaskConfigStore()
      const normalized = store.normalizeSnapshot(undefined)

      expect(normalized.taskOrder).toEqual(["task-a", "task-b", "task-c"])
      expect(normalized.taskChecked).toEqual({
        "task-a": false,
        "task-b": false,
        "task-c": false,
      })
      expect(normalized.taskOptions).toEqual({
        "task-a": {
          difficulty: "normal",
          params: { host: "localhost", port: "" },
        },
        "task-b": { mode: ["auto"] },
        "task-c": {},
      })
      expect(normalized.preTasks).toEqual([])
    })

    it("filters invalid preTasks and fills in missing defaults", () => {
      const store = initTaskConfigStore()
      const normalized = store.normalizeSnapshot({
        taskOrder: ["task-b"],
        taskChecked: { "task-b": true },
        taskOptions: { "task-b": { mode: ["manual"] } },
        preTasks: [
          { id: "", command: "", enabled: true, timeout: 30 },
          { id: "", command: "valid-command", enabled: false, timeout: 10 },
          // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
          { id: "has-id", command: "another", enabled: "yes" as unknown as boolean, timeout: -1 },
        ],
      })

      expect(normalized.preTasks).toHaveLength(2)
      expect(normalized.preTasks[0]).toEqual({
        id: "mock-uuid",
        command: "valid-command",
        enabled: false,
        timeout: 10,
      })
      expect(normalized.preTasks[1]).toEqual({
        id: "has-id",
        command: "another",
        enabled: true,
        timeout: 30,
      })
    })

    it("passes through valid preTasks as copies", () => {
      const store = initTaskConfigStore()
      const original = [{ id: "pt1", command: "echo ok", enabled: true, timeout: 30 }]
      const normalized = store.normalizeSnapshot({
        taskOrder: [],
        taskChecked: {},
        taskOptions: {},
        preTasks: original,
      })

      expect(normalized.preTasks).toEqual(original)
      expect(normalized.preTasks).not.toBe(original)
      expect(normalized.preTasks[0]).not.toBe(original[0])
    })
  })

  describe("hydrateSnapshot", () => {
    it("restores task list, options and preTasks from the snapshot", () => {
      const store = initTaskConfigStore()
      const snapshot = {
        taskOrder: ["task-c", "task-a", "task-b"],
        taskChecked: { "task-c": true, "task-a": true, "task-b": false },
        taskOptions: {
          "task-a": { difficulty: "hard", params: { host: "remote", port: "8080" } },
          "task-b": { mode: ["manual"] },
        },
        preTasks: [{ id: "pt1", command: "echo hydrate", enabled: true, timeout: 30 }],
      }

      store.hydrateSnapshot(snapshot)

      expect(store.taskList.map((t) => ({ id: t.id, checked: t.checked }))).toEqual([
        { id: "task-c", checked: true },
        { id: "task-a", checked: true },
        { id: "task-b", checked: false },
      ])
      expect(store.options["task-a"]).toEqual({
        difficulty: "hard",
        params: { host: "remote", port: "8080" },
      })
      expect(store.options["task-b"]).toEqual({ mode: ["manual"] })
      expect(store.preTasks).toEqual(snapshot.preTasks)
      expect(store.preTasks).not.toBe(snapshot.preTasks)
    })
  })

  describe("buildExecutionPayload", () => {
    it("returns normalized task list, merged options and a copy of preTasks", () => {
      const store = initTaskConfigStore()
      store.options["task-a"] = { ...store.options["task-a"], difficulty: "hard" }
      store.preTasks = [{ id: "pt1", command: "echo run", enabled: true, timeout: 30 }]

      const payload = store.buildExecutionPayload(["task-a", "invalid-task", "task-b", "task-a"])

      expect(payload.task_list).toEqual(["task-a", "task-b"])
      expect(payload.task_options).toEqual({
        "task-a": {
          difficulty: "hard",
          params: { host: "localhost", port: "" },
        },
        "task-b": { mode: ["auto"] },
      })
      expect(payload.preTasks).toEqual(store.preTasks)
      expect(payload.preTasks).not.toBe(store.preTasks)
    })
  })

  describe("buildOptionsForTasks", () => {
    it("merges defaults, current values and overrides with overrides winning", () => {
      const store = initTaskConfigStore()
      store.options["task-a"] = { ...store.options["task-a"], difficulty: "easy" }

      const result = store.buildOptionsForTasks(["task-a"], {
        "task-a": { difficulty: "hard", params: { host: "override-host" } },
      })

      expect(result["task-a"]).toEqual({
        difficulty: "hard",
        params: { host: "override-host" },
      })
    })

    it("ignores option keys that are not present in defaults", () => {
      const store = initTaskConfigStore()
      const result = store.buildOptionsForTasks(["task-a"], {
        "task-a": { unknownKey: "ignored" },
      })

      expect(result["task-a"]).not.toHaveProperty("unknownKey")
    })
  })

  describe("buildOptionsFromPersisted", () => {
    it("merges defaults with persisted values, persisted wins when valid", () => {
      const store = initTaskConfigStore()
      const result = store.buildOptionsFromPersisted(["task-a"], {
        "task-a": { difficulty: "hard" },
      })

      expect(result["task-a"]).toEqual({
        difficulty: "hard",
        params: { host: "localhost", port: "" },
      })
    })

    it("filters unknown persisted keys", () => {
      const store = initTaskConfigStore()
      const result = store.buildOptionsFromPersisted(["task-a"], {
        "task-a": { difficulty: "hard", unknownKey: "ignored" },
      })

      expect(result["task-a"]).not.toHaveProperty("unknownKey")
    })
  })

  describe("debouncedSave", () => {
    it("calls saveConfig after a 500ms delay", async () => {
      vi.useFakeTimers()
      const store = initTaskConfigStore()
      const saveSpy = vi.spyOn(store, "saveConfig").mockResolvedValue(undefined)

      store.debouncedSave()
      expect(saveSpy).not.toHaveBeenCalled()

      await vi.advanceTimersByTimeAsync(500)
      expect(saveSpy).toHaveBeenCalledTimes(1)

      vi.useRealTimers()
    })

    it("cancels the previous timer when called again within 500ms", async () => {
      vi.useFakeTimers()
      const store = initTaskConfigStore()
      const saveSpy = vi.spyOn(store, "saveConfig").mockResolvedValue(undefined)

      store.debouncedSave()
      await vi.advanceTimersByTimeAsync(250)
      store.debouncedSave()
      await vi.advanceTimersByTimeAsync(250)

      expect(saveSpy).not.toHaveBeenCalled()

      await vi.advanceTimersByTimeAsync(250)
      expect(saveSpy).toHaveBeenCalledTimes(1)

      vi.useRealTimers()
    })
  })

  describe("loadConfig", () => {
    it("fetches config, seeds snapshots, hydrates selected preset and sets loaded", async () => {
      const store = useTaskConfigStore()
      vi.mocked(api.getTaskConfig).mockResolvedValue({
        selectedPreset: "preset2",
        presets: {
          preset2: {
            taskOrder: ["task-b"],
            taskChecked: { "task-b": true },
            taskOptions: { "task-b": { mode: ["manual"] } },
            preTasks: [],
          },
        },
      })

      await store.loadConfig()

      expect(api.getTaskConfig).toHaveBeenCalledTimes(1)
      expect(store.selectedPresetName).toBe("preset2")
      expect(store.configLoaded).toBe(true)
      expect(store.taskList.map((t) => t.id)).toEqual(["task-b", "task-a", "task-c"])
      expect(store.taskList.find((t) => t.id === "task-b")?.checked).toBe(true)
      expect(store.options["task-b"]).toEqual({ mode: ["manual"] })
    })

    it("falls back to custom preset when the API returns an empty config", async () => {
      const store = useTaskConfigStore()
      vi.mocked(api.getTaskConfig).mockResolvedValue({
        selectedPreset: "",
        presets: {},
      })

      await store.loadConfig()

      expect(store.selectedPresetName).toBe(CUSTOM_PRESET_NAME)
      expect(store.configLoaded).toBe(true)
      expect(store.taskList.map((t) => t.id)).toEqual(["task-a", "task-b", "task-c"])
      expect(store.taskList.every((t) => !t.checked)).toBe(true)
    })
  })

  describe("resetConfig", () => {
    it("calls resetTaskConfig API and resets to custom preset with empty preTasks", async () => {
      const store = initTaskConfigStore()
      store.selectPreset("preset1")
      store.preTasks = [{ id: "pt1", command: "echo old", enabled: true, timeout: 30 }]
      vi.mocked(api.resetTaskConfig).mockResolvedValue(true)

      await store.resetConfig()

      expect(api.resetTaskConfig).toHaveBeenCalledTimes(1)
      expect(store.selectedPresetName).toBe(CUSTOM_PRESET_NAME)
      expect(store.preTasks).toEqual([])
      expect(store.taskList.map((t) => t.id)).toEqual(["task-a", "task-b", "task-c"])
      expect(store.taskList.every((t) => !t.checked)).toBe(true)
    })
  })

  describe("syncCurrentPresetSnapshot", () => {
    it("updates the snapshot for the currently selected preset", () => {
      const store = initTaskConfigStore()
      store.taskList.find((t) => t.id === "task-a")!.checked = true
      store.options["task-a"] = { ...store.options["task-a"], difficulty: "hard" }
      store.preTasks = [{ id: "pt1", command: "echo sync", enabled: true, timeout: 30 }]

      store.syncCurrentPresetSnapshot()

      const snapshot = store.presetSnapshots[CUSTOM_PRESET_NAME]
      expect(snapshot.taskChecked["task-a"]).toBe(true)
      expect(snapshot.taskOptions["task-a"]).toMatchObject({ difficulty: "hard" })
      expect(snapshot.preTasks).toEqual(store.preTasks)
    })
  })
})
