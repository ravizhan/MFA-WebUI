import { describe, expect, it, beforeEach, afterEach, vi } from "vitest"
import { setActivePinia, createPinia } from "pinia"
import { nextTick } from "vue"

vi.mock("@/services/api", () => ({
  getDeviceState: vi.fn<() => void>(),
  getDevices: vi.fn<() => void>(),
  getResource: vi.fn<() => void>(),
  postDevices: vi.fn<() => void>(),
  postResource: vi.fn<() => void>(),
  startTask: vi.fn<() => void>(),
  getSettings: vi.fn<() => void>(),
  updateSettings: vi.fn<() => void>(),
  getTaskConfig: vi.fn<() => void>(),
  saveTaskConfig: vi.fn<() => void>(),
  getInterface: vi.fn<() => void>(),
  rescanScanSelectOption: vi.fn<() => void>(),
}))

vi.mock("@/services/feedback/message", () => ({
  showGlobalMessage: vi.fn<() => void>(),
}))

vi.mock("vue-i18n", () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

import { useDeviceConnectionStore } from "@/stores/device/deviceConnection"
import { useIndexStore } from "@/stores/panel/session"
import { useInterfaceStore } from "@/stores/interface/interface"
import { useSettingsStore } from "@/stores/settings/settings"
import { useTaskConfigStore } from "@/stores/task-config/taskConfig"
import * as api from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import type {
  ConnectableDevice,
  DeviceControllerCapability,
  DeviceRuntimeState,
  DeviceSearchData,
  ResourceInfo,
} from "@/services/api"
import type { PanelLastConnectedDevice } from "@/types/settingsModel"

const disconnectedState: DeviceRuntimeState = {
  connected: false,
  configuration_locked: false,
  controller_name: null,
  resource_name: null,
}

const lockedAdbState: DeviceRuntimeState = {
  connected: true,
  configuration_locked: true,
  controller_name: "adb",
  resource_name: "res1",
}

const adbCapability: DeviceControllerCapability = {
  name: "adb",
  type: "Adb",
  label: "Adb",
  display_label: "ADB",
  enabled: true,
  reason: "",
  search_mode: "select",
  default_address: "",
}

const playCoverCapability: DeviceControllerCapability = {
  name: "playcover",
  type: "PlayCover",
  label: "PlayCover",
  display_label: "PlayCover",
  enabled: true,
  reason: "",
  search_mode: "input",
  default_address: "127.0.0.1:1717",
}

const adbDevice: ConnectableDevice = {
  type: "Adb",
  name: "adb-device",
  adb_path: "/usr/bin/adb",
  address: "127.0.0.1:5555",
  screencap_methods: "",
  input_methods: "",
  config: {},
}

const savedAdbDevice: PanelLastConnectedDevice = {
  type: "Adb",
  controller_name: "adb",
  fingerprint: "adb|/usr/bin/adb|127.0.0.1:5555",
  adb_path: "/usr/bin/adb",
  address: "127.0.0.1:5555",
  class_name: "",
  window_name: "",
  hWnd: 0,
  gamepad_type: 0,
  uuid: "",
}

describe("useDeviceConnectionStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetAllMocks()
    vi.mocked(api.getDeviceState).mockResolvedValue(disconnectedState)
    vi.mocked(api.getDevices).mockResolvedValue({
      controllers: [],
      selected_controller: null,
      devices: [],
    })
    vi.mocked(api.getResource).mockResolvedValue([])
    vi.mocked(api.updateSettings).mockResolvedValue(true)
  })

  afterEach(() => {
    const store = useDeviceConnectionStore()
    store.cleanup()
  })

  it("has correct initial state", () => {
    const store = useDeviceConnectionStore()
    expect(store.selectedController).toBeNull()
    expect(store.availableDevices).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.isDeviceResourceLocked).toBe(false)
  })

  describe("applyDeviceRuntimeState", () => {
    it("sets locked state and names when connected and locked", () => {
      const store = useDeviceConnectionStore()
      store.applyDeviceRuntimeState(lockedAdbState)
      expect(store.isDeviceResourceLocked).toBe(true)
      expect(store.connectedControllerName).toBe("adb")
      expect(store.connectedResourceName).toBe("res1")
    })

    it("hydrates selected controller from runtime state when locked", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.applyDeviceRuntimeState({
        connected: true,
        configuration_locked: true,
        controller_name: "adb",
        resource_name: null,
      })
      expect(store.selectedController).toBe("ADB")
    })

    it("hydrates resource from runtime state when locked", () => {
      const store = useDeviceConnectionStore()
      store.applyDeviceRuntimeState({
        connected: true,
        configuration_locked: true,
        controller_name: null,
        resource_name: "res1",
      })
      expect(store.resource).toBe("res1")
    })

    it("does not lock when not connected even if configuration_locked is true", () => {
      const store = useDeviceConnectionStore()
      store.applyDeviceRuntimeState({
        connected: false,
        configuration_locked: true,
        controller_name: "adb",
        resource_name: "res1",
      })
      expect(store.isDeviceResourceLocked).toBe(false)
    })
  })

  describe("StartTask", () => {
    it("returns false when device connection fails", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      vi.mocked(api.getDeviceState).mockResolvedValue(disconnectedState)
      vi.mocked(api.postDevices).mockResolvedValue({
        success: false,
        message: "connect failed",
      })
      const result = await store.StartTask()
      expect(result).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "设备连接失败: connect failed")
    })

    it("returns false when resource selection fails", async () => {
      const store = useDeviceConnectionStore()
      const indexStore = useIndexStore()
      const settingsStore = useSettingsStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      store.resource = "res1"
      indexStore.Connected = true
      settingsStore.settings.panel.lastConnectedDevice = savedAdbDevice
      vi.mocked(api.getDeviceState).mockResolvedValue({
        connected: true,
        configuration_locked: false,
        controller_name: null,
        resource_name: null,
      })
      vi.mocked(api.postDevices).mockResolvedValue({ success: true, message: "ok" })
      vi.mocked(api.postResource).mockResolvedValue({
        success: false,
        message: "resource failed",
      })
      const result = await store.StartTask()
      expect(result).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "资源设置失败: resource failed")
    })

    it("returns false when no compatible tasks", async () => {
      const store = useDeviceConnectionStore()
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      configStore.configLoaded = true
      configStore.taskList = [{ id: "task1", name: "Task 1", order: 0, checked: true }]

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1", controller: ["win32"] }],
      }
      vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
      vi.spyOn(store, "connectDevices").mockResolvedValue({ success: true, message: "ok" })
      vi.spyOn(store, "postResourceSelection").mockResolvedValue({
        success: true,
        message: "ok",
      })
      const result = await store.StartTask()
      expect(result).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "panel.noCompatibleTask")
    })

    it("returns false when no tasks selected", async () => {
      const store = useDeviceConnectionStore()
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      configStore.configLoaded = true
      configStore.taskList = [{ id: "task1", name: "Task 1", order: 0, checked: false }]

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
      vi.spyOn(store, "connectDevices").mockResolvedValue({ success: true, message: "ok" })
      vi.spyOn(store, "postResourceSelection").mockResolvedValue({
        success: true,
        message: "ok",
      })
      const result = await store.StartTask()
      expect(result).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "panel.selectTask")
    })

    it("returns true on full success", async () => {
      const store = useDeviceConnectionStore()
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      const payload = { task_list: ["task1"], task_options: {}, preTasks: [] }
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      configStore.configLoaded = true
      configStore.taskList = [{ id: "task1", name: "Task 1", order: 0, checked: true }]

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
      vi.spyOn(configStore, "buildExecutionPayload").mockReturnValue(payload)
      vi.mocked(api.startTask).mockResolvedValue(true)
      const result = await store.StartTask()
      expect(result).toBe(true)
      expect(api.startTask).toHaveBeenCalledWith(payload)
    })

    it("skips connect and resource when already connected", async () => {
      const store = useDeviceConnectionStore()
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      const payload = { task_list: ["task1"], task_options: {}, preTasks: [] }
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      configStore.configLoaded = true
      configStore.taskList = [{ id: "task1", name: "Task 1", order: 0, checked: true }]

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
      vi.spyOn(configStore, "buildExecutionPayload").mockReturnValue(payload)
      const connectSpy = vi.spyOn(store, "connectDevices").mockResolvedValue({
        success: true,
        message: "ok",
      })
      const resourceSpy = vi.spyOn(store, "postResourceSelection").mockResolvedValue({
        success: true,
        message: "ok",
      })
      vi.mocked(api.startTask).mockResolvedValue(true)
      const result = await store.StartTask()
      expect(result).toBe(true)
      expect(connectSpy).not.toHaveBeenCalled()
      expect(resourceSpy).not.toHaveBeenCalled()
    })
  })

  describe("fetchDevices", () => {
    it("ignores stale response when a newer request completes first", async () => {
      const store = useDeviceConnectionStore()
      let resolve1: (value: DeviceSearchData) => void
      let resolve2: (value: DeviceSearchData) => void
      const p1 = new Promise<DeviceSearchData>((r) => {
        resolve1 = r
      })
      const p2 = new Promise<DeviceSearchData>((r) => {
        resolve2 = r
      })
      vi.mocked(api.getDevices)
        .mockImplementationOnce(() => p1)
        .mockImplementationOnce(() => p2)
      const promise1 = store.fetchDevices()
      const promise2 = store.fetchDevices()
      resolve2!({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [adbDevice],
      })
      await promise2
      resolve1!({
        controllers: [],
        selected_controller: null,
        devices: [],
      })
      await promise1
      expect(store.controllerCapabilities).toEqual([adbCapability])
      expect(store.availableDevices).toEqual([adbDevice])
      expect(store.loading).toBe(false)
    })
  })

  describe("getResourceList", () => {
    it("ignores stale response when a newer request completes first", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      let resolve1: (value: ResourceInfo[]) => void
      let resolve2: (value: ResourceInfo[]) => void
      const p1 = new Promise<ResourceInfo[]>((r) => {
        resolve1 = r
      })
      const p2 = new Promise<ResourceInfo[]>((r) => {
        resolve2 = r
      })
      vi.mocked(api.getResource)
        .mockImplementationOnce(() => p1)
        .mockImplementationOnce(() => p2)
      const promise1 = store.getResourceList()
      const promise2 = store.getResourceList()
      resolve2!([{ name: "res2" }])
      await promise2
      resolve1!([{ name: "res1" }])
      await promise1
      expect(store.resourcesList).toEqual([{ label: "res2", value: "res2" }])
      expect(store.loading).toBe(false)
    })
  })

  describe("connectDevices", () => {
    it("fails when device resource is locked", async () => {
      const store = useDeviceConnectionStore()
      store.isDeviceResourceLocked = true
      const result = await store.connectDevices()
      expect(result.success).toBe(false)
      expect(result.message).toBe("设备与资源已锁定，无法切换")
    })

    it("fails when no controller selected", async () => {
      const store = useDeviceConnectionStore()
      const result = await store.connectDevices()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.selectDeviceType")
    })

    it("fails when selected controller is disabled", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [{ ...adbCapability, enabled: false }]
      store.selectedController = "ADB"
      const result = await store.connectDevices()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.selectDeviceType")
    })

    it("PlayCover fails on empty address", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [playCoverCapability]
      store.selectedController = "PlayCover"
      store.playCoverAddress = "  "
      const result = await store.connectDevices()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.playcoverAddress")
    })

    it("PlayCover fails on invalid address format", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [playCoverCapability]
      store.selectedController = "PlayCover"
      store.playCoverAddress = "bad-address"
      const result = await store.connectDevices()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.invalidPlaycoverAddress")
    })

    it("fails when no device selected for non-PlayCover controller", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = null
      const result = await store.connectDevices()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.selectDevice")
    })

    it("succeeds and persists device on valid selection", async () => {
      const store = useDeviceConnectionStore()
      const settingsStore = useSettingsStore()
      const indexStore = useIndexStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      vi.mocked(api.getDeviceState).mockResolvedValue({
        connected: true,
        configuration_locked: true,
        controller_name: "adb",
        resource_name: "res1",
      })
      vi.mocked(api.postDevices).mockResolvedValue({ success: true, message: "ok" })
      vi.mocked(api.getResource).mockResolvedValue([{ name: "res1" }])
      const result = await store.connectDevices()
      expect(result.success).toBe(true)
      expect(api.postDevices).toHaveBeenCalledWith({
        controller_name: "adb",
        device: adbDevice,
      })
      expect(indexStore.Connected).toBe(true)
      expect(settingsStore.settings.panel.lastConnectedDevice).not.toBeNull()
      expect(store.resourcesList).toEqual([{ label: "res1", value: "res1" }])
    })
  })

  describe("postResourceSelection", () => {
    it("fails when locked", async () => {
      const store = useDeviceConnectionStore()
      store.isDeviceResourceLocked = true
      const result = await store.postResourceSelection()
      expect(result.success).toBe(false)
    })

    it("fails when not connected", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      const result = await store.postResourceSelection()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.connectFirstHint")
    })

    it("fails when no resource selected", async () => {
      const store = useDeviceConnectionStore()
      const indexStore = useIndexStore()
      const settingsStore = useSettingsStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      indexStore.Connected = true
      settingsStore.settings.panel.lastConnectedDevice = savedAdbDevice
      const result = await store.postResourceSelection()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.selectResource")
    })

    it("succeeds when connected and resource selected", async () => {
      const store = useDeviceConnectionStore()
      const indexStore = useIndexStore()
      const settingsStore = useSettingsStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      store.resource = "res1"
      indexStore.Connected = true
      settingsStore.settings.panel.lastConnectedDevice = savedAdbDevice
      vi.mocked(api.postResource).mockResolvedValue({ success: true, message: "ok" })
      const result = await store.postResourceSelection()
      expect(result.success).toBe(true)
      expect(api.postResource).toHaveBeenCalledWith("res1")
    })
  })

  describe("init and cleanup", () => {
    it("init sets up timer and watchers, double init is no-op", async () => {
      const store = useDeviceConnectionStore()
      const settingsStore = useSettingsStore()
      const indexStore = useIndexStore()
      const configStore = useTaskConfigStore()
      settingsStore.initialized = true
      const setIntervalSpy = vi.spyOn(window, "setInterval")
      store.init()
      expect(store.initialized).toBe(true)
      expect(store.deviceStatePollTimer).not.toBeNull()
      expect(setIntervalSpy).toHaveBeenCalledTimes(1)
      store.init()
      expect(setIntervalSpy).toHaveBeenCalledTimes(1)
      configStore.taskList = [{ id: "task1", name: "Task 1", order: 0 }]
      await nextTick()
      expect(indexStore.SelectedTaskID).toBe("task1")
      setIntervalSpy.mockRestore()
    })

    it("cleanup clears timer and resets initialized", () => {
      const store = useDeviceConnectionStore()
      const settingsStore = useSettingsStore()
      settingsStore.initialized = true
      store.init()
      expect(store.deviceStatePollTimer).not.toBeNull()
      store.cleanup()
      expect(store.deviceStatePollTimer).toBeNull()
      expect(store.initialized).toBe(false)
    })
  })

  describe("getters", () => {
    it("controllerOptions maps capabilities", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [
        adbCapability,
        { ...adbCapability, display_label: "ADB 2", enabled: false },
      ]
      expect(store.controllerOptions).toEqual([
        { label: "ADB", value: "ADB", disabled: false },
        { label: "ADB 2", value: "ADB 2", disabled: true },
      ])
    })

    it("selectedControllerCapability finds by display_label", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      expect(store.selectedControllerCapability).toEqual(adbCapability)
    })

    it("selectedControllerDisabled returns true for disabled capability", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [{ ...adbCapability, enabled: false }]
      store.selectedController = "ADB"
      expect(store.selectedControllerDisabled).toBe(true)
    })

    it("selectedControllerName returns capability name or null", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      expect(store.selectedControllerName).toBe("adb")
      store.selectedController = null
      expect(store.selectedControllerName).toBeNull()
    })
  })
})
