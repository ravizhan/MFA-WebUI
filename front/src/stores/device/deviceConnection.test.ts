import { describe, expect, it, beforeEach, afterEach, vi } from "vitest"
import { setActivePinia, createPinia } from "pinia"
import { nextTick } from "vue"

vi.mock("@/services/api", () => ({
  getDeviceState: vi.fn<() => void>(),
  getDevices: vi.fn<() => void>(),
  getResource: vi.fn<() => void>(),
  postDevices: vi.fn<() => void>(),
  postCustomDevice: vi.fn<() => void>(),
  postResource: vi.fn<() => void>(),
  startTask: vi.fn<() => void>(),
  stopTask: vi.fn<() => void>(),
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

vi.mock("@/app/i18n", () => ({
  default: { global: { t: (key: string) => key } },
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
import type { ManualStartPayload, StartConflict } from "@/types/schedulerModel"
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
  screencap_methods: 0,
  input_methods: 0,
  config: {},
}

const customAdbDevice: ConnectableDevice = {
  type: "Adb",
  name: "",
  adb_path: "",
  address: "192.168.1.10:5555",
  screencap_methods: 0,
  input_methods: 0,
  config: {},
}

const scannedCustomAdbDevice: ConnectableDevice = {
  type: "Adb",
  name: "phone",
  adb_path: "/usr/bin/adb",
  address: "192.168.1.10:5555",
  screencap_methods: 1,
  input_methods: 1,
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

  describe("applyDeviceRuntimeState", () => {
    it("applies lock authority from backend and does not lock when disconnected", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability, playCoverCapability]
      store.selectedController = "PlayCover"
      store.resource = "local-res"

      store.applyDeviceRuntimeState(lockedAdbState)
      expect(store.isDeviceResourceLocked).toBe(true)
      expect(store.connectedControllerName).toBe("adb")
      expect(store.connectedResourceName).toBe("res1")
      expect(store.selectedController).toBe("ADB")
      expect(store.resource).toBe("res1")

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
    function setupReadyToStart() {
      const store = useDeviceConnectionStore()
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      store.resource = "res1"
      configStore.configLoaded = true
      configStore.taskList = [{ id: "task1", name: "Task 1", order: 0, checked: true }]
      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
      return { store, configStore, interfaceStore }
    }

    const expectedStartPayload: ManualStartPayload = {
      task_list: ["task1"],
      task_options: {},
      preTasks: [{ id: "pre-1", command: "echo pre", timeout: 5, enabled: true }],
      controller_name: "adb",
      device: {
        controller_name: "adb",
        device_type: "Adb",
        device_address: "127.0.0.1:5555",
      },
      resource_name: "res1",
    }

    it("guards missing device/resource/compatible/selected tasks", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = null
      store.resource = "res1"
      vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
      expect(await store.StartTask()).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "panel.selectDevice")
      expect(api.startTask).not.toHaveBeenCalled()

      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      store.resource = null
      vi.mocked(api.getDeviceState).mockResolvedValue({
        connected: true,
        configuration_locked: true,
        controller_name: "adb",
        resource_name: null,
      })
      expect(await store.StartTask()).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "panel.selectResource")

      const ready = setupReadyToStart()
      ready.interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1", controller: ["win32"] }],
      }
      expect(await ready.store.StartTask()).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "panel.noCompatibleTask")

      ready.interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      ready.configStore.taskList = [{ id: "task1", name: "Task 1", order: 0, checked: false }]
      expect(await ready.store.StartTask()).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "panel.selectTask")
    })

    it("returns true on full success and records conflict when rejected", async () => {
      const { store, configStore } = setupReadyToStart()
      const indexStore = useIndexStore()
      vi.spyOn(configStore, "buildExecutionPayload").mockReturnValue({
        task_list: ["task1"],
        task_options: {},
        preTasks: [{ id: "pre-1", command: "echo pre", timeout: 5, enabled: true }],
      })
      vi.mocked(api.startTask).mockResolvedValueOnce({ accepted: true, runId: "run-1" })
      expect(await store.StartTask()).toBe(true)
      expect(api.startTask).toHaveBeenCalledWith(expectedStartPayload)
      expect(store.startConflict).toBeNull()
      expect(indexStore.TaskRunning).toBe(false)

      const conflict: StartConflict = {
        code: "busy_manual",
        message: "busy",
        active_run_id: "run-active",
        active_task_name: "Other",
        active_origin: "manual",
      }
      vi.mocked(api.startTask).mockResolvedValueOnce({ accepted: false, conflict })
      expect(await store.StartTask()).toBe(false)
      expect(store.startConflict).toEqual(conflict)
    })

    it("stopActiveAndRestart stops then retries, and fails when stop fails", async () => {
      const { store, configStore } = setupReadyToStart()
      const indexStore = useIndexStore()
      const conflict: StartConflict = {
        code: "busy_scheduled",
        message: "scheduled running",
        active_run_id: "run-sched",
        active_task_name: "Sched",
        active_origin: "in_app",
      }
      store.startConflict = conflict
      vi.spyOn(configStore, "buildExecutionPayload").mockReturnValue({
        task_list: ["task1"],
        task_options: {},
        preTasks: [{ id: "pre-1", command: "echo pre", timeout: 5, enabled: true }],
      })
      vi.mocked(api.stopTask).mockResolvedValueOnce(true)
      vi.mocked(api.startTask).mockResolvedValueOnce({ accepted: true, runId: "run-2" })

      expect(await store.stopActiveAndRestart()).toBe(true)
      expect(api.stopTask).toHaveBeenCalledOnce()
      expect(api.startTask).toHaveBeenCalledWith(expectedStartPayload)
      expect(store.startConflict).toBeNull()
      expect(indexStore.TaskRunning).toBe(false)

      store.startConflict = conflict
      vi.mocked(api.stopTask).mockResolvedValueOnce(false)
      expect(await store.stopActiveAndRestart()).toBe(false)
      expect(store.startConflict).not.toBeNull()
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

    it("re-hydrates locked selection after capabilities load", async () => {
      const store = useDeviceConnectionStore()
      store.isDeviceResourceLocked = true
      store.connectedControllerName = "adb"
      store.connectedResourceName = "res1"
      store.selectedController = "PlayCover"
      store.resource = "stale"
      vi.mocked(api.getDevices).mockResolvedValue({
        controllers: [adbCapability, playCoverCapability],
        selected_controller: "playcover",
        devices: [],
      })
      await store.fetchDevices()
      expect(store.selectedController).toBe("ADB")
      expect(store.resource).toBe("res1")
    })
  })

  describe("openDevices", () => {
    it("refreshes devices for non-PlayCover controller and is no-op when locked/PlayCover", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      vi.mocked(api.getDevices).mockResolvedValue({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [adbDevice],
      })
      store.openDevices()
      await vi.waitFor(() => {
        expect(store.availableDevices).toEqual([adbDevice])
      })
      expect(api.getDevices).toHaveBeenCalledWith("adb")

      vi.mocked(api.getDevices).mockClear()
      store.isDeviceResourceLocked = true
      store.openDevices()
      expect(api.getDevices).not.toHaveBeenCalled()

      store.isDeviceResourceLocked = false
      store.controllerCapabilities = [playCoverCapability]
      store.selectedController = "PlayCover"
      store.openDevices()
      expect(api.getDevices).not.toHaveBeenCalled()
    })
  })

  describe("createCustomDevice", () => {
    it("saves trimmed address, refreshes, and selects richer scanned device", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      vi.mocked(api.postCustomDevice).mockResolvedValue({
        success: true,
        message: "ok",
        data: customAdbDevice,
      })
      vi.mocked(api.getDevices).mockResolvedValue({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [scannedCustomAdbDevice],
      })

      await store.createCustomDevice("  192.168.1.10:5555  ")

      expect(api.postCustomDevice).toHaveBeenCalledWith({
        controller_name: "adb",
        type: "Adb",
        address: "192.168.1.10:5555",
      })
      expect(api.getDevices).toHaveBeenCalledWith("adb")
      expect(store.availableDevices).toEqual([scannedCustomAdbDevice])
      expect(store.selectedDeviceKey).toBe("adb|/usr/bin/adb|192.168.1.10:5555")
    })

    it("reports error when refresh omits device or save fails; ignores empty/locked", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]

      vi.mocked(api.postCustomDevice).mockResolvedValueOnce({
        success: true,
        message: "ok",
        data: customAdbDevice,
      })
      vi.mocked(api.getDevices).mockResolvedValueOnce({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [adbDevice],
      })
      await store.createCustomDevice("192.168.1.10:5555")
      expect(store.availableDevices).not.toContainEqual(customAdbDevice)
      expect(showGlobalMessage).toHaveBeenCalledWith(
        "error",
        "自定义设备已保存，但刷新列表后未找到该设备",
      )

      vi.mocked(api.postCustomDevice).mockResolvedValueOnce({
        success: false,
        message: "save failed",
      })
      await store.createCustomDevice("192.168.1.10:5555")
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "save failed")
      expect(store.selectedDeviceKey).toBe("adb|/usr/bin/adb|127.0.0.1:5555")

      vi.mocked(api.postCustomDevice).mockClear()
      await store.createCustomDevice("   ")
      store.isDeviceResourceLocked = true
      await store.createCustomDevice("192.168.1.10:5555")
      expect(api.postCustomDevice).not.toHaveBeenCalled()
    })

    it("does not reselect when controller changes after POST", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability, playCoverCapability]
      store.selectedController = "ADB"
      let resolvePost: (value: {
        success: boolean
        message: string
        data?: ConnectableDevice
      }) => void
      const postPromise = new Promise<{
        success: boolean
        message: string
        data?: ConnectableDevice
      }>((r) => {
        resolvePost = r
      })
      vi.mocked(api.postCustomDevice).mockImplementationOnce(() => postPromise)

      const createPromise = store.createCustomDevice("192.168.1.10:5555")
      store.selectedController = "PlayCover"
      resolvePost!({ success: true, message: "ok", data: customAdbDevice })
      await createPromise

      expect(api.getDevices).not.toHaveBeenCalled()
      expect(store.selectedController).toBe("PlayCover")
    })

    it("does not reselect when a newer fetchDevices wins race after create", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"

      let resolvePost: (value: {
        success: boolean
        message: string
        data?: ConnectableDevice
      }) => void
      const postPromise = new Promise<{
        success: boolean
        message: string
        data?: ConnectableDevice
      }>((r) => {
        resolvePost = r
      })
      vi.mocked(api.postCustomDevice).mockImplementationOnce(() => postPromise)

      let resolveCreateFetch: (value: DeviceSearchData) => void
      let resolveNewerFetch: (value: DeviceSearchData) => void
      const createFetch = new Promise<DeviceSearchData>((r) => {
        resolveCreateFetch = r
      })
      const newerFetch = new Promise<DeviceSearchData>((r) => {
        resolveNewerFetch = r
      })
      vi.mocked(api.getDevices)
        .mockImplementationOnce(() => createFetch)
        .mockImplementationOnce(() => newerFetch)

      const createPromise = store.createCustomDevice("192.168.1.10:5555")
      resolvePost!({ success: true, message: "ok", data: customAdbDevice })
      await Promise.resolve()
      await Promise.resolve()

      const newerPromise = store.fetchDevices("adb")
      resolveNewerFetch!({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [adbDevice],
      })
      await newerPromise
      resolveCreateFetch!({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [scannedCustomAdbDevice],
      })
      await createPromise

      expect(store.availableDevices).toEqual([adbDevice])
      expect(store.selectedDeviceKey).not.toBe("adb|/usr/bin/adb|192.168.1.10:5555")
    })
  })

  describe("selectedDevice rebind", () => {
    it("rebinds by identity, clears missing selection, never treats fingerprint as address", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.availableDevices = [customAdbDevice]
      store.selectedDeviceKey = "adb||192.168.1.10:5555"

      vi.mocked(api.getDevices).mockResolvedValueOnce({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [scannedCustomAdbDevice],
      })
      await store.fetchDevices("adb")
      expect(store.selectedDeviceKey).toBe("adb|/usr/bin/adb|192.168.1.10:5555")
      expect(store.selectedDevice).toEqual(scannedCustomAdbDevice)

      store.availableDevices = [adbDevice]
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      vi.mocked(api.getDevices).mockResolvedValueOnce({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [customAdbDevice],
      })
      await store.fetchDevices("adb")
      expect(store.selectedDeviceKey).toBeNull()
      expect(store.selectedDevice).toBeNull()

      store.availableDevices = [adbDevice]
      store.selectedDeviceKey = "adb|/missing/path|127.0.0.1:5555"
      expect(store.selectedDevice).toBeNull()
    })
  })

  describe("deviceOptions", () => {
    it("maps availableDevices and returns disabled placeholder when empty", () => {
      const store = useDeviceConnectionStore()
      store.availableDevices = [adbDevice, customAdbDevice]
      expect(store.deviceOptions).toEqual([
        { label: "adb-device(127.0.0.1:5555)", value: "adb|/usr/bin/adb|127.0.0.1:5555" },
        { label: "192.168.1.10:5555", value: "adb||192.168.1.10:5555" },
      ])

      store.availableDevices = []
      expect(store.deviceOptions).toEqual([
        { label: "panel.noDevice", value: "none-device", disabled: true },
      ])
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
    it("guards locked/missing/disabled/PlayCover validation and succeeds on valid selection", async () => {
      const store = useDeviceConnectionStore()

      store.isDeviceResourceLocked = true
      expect(await store.connectDevices()).toEqual({
        success: false,
        message: "设备与资源已锁定，无法切换",
      })
      store.isDeviceResourceLocked = false

      expect((await store.connectDevices()).message).toBe("panel.selectDeviceType")

      store.controllerCapabilities = [{ ...adbCapability, enabled: false }]
      store.selectedController = "ADB"
      expect((await store.connectDevices()).message).toBe("panel.selectDeviceType")

      store.controllerCapabilities = [playCoverCapability]
      store.selectedController = "PlayCover"
      store.playCoverAddress = "  "
      expect((await store.connectDevices()).message).toBe("panel.playcoverAddress")
      store.playCoverAddress = "bad-address"
      expect((await store.connectDevices()).message).toBe("panel.invalidPlaycoverAddress")

      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = null
      expect((await store.connectDevices()).message).toBe("panel.selectDevice")

      const settingsStore = useSettingsStore()
      const indexStore = useIndexStore()
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
    it("guards locked/not-connected/missing resource and succeeds when valid", async () => {
      const store = useDeviceConnectionStore()
      store.isDeviceResourceLocked = true
      expect((await store.postResourceSelection()).success).toBe(false)

      store.isDeviceResourceLocked = false
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      expect((await store.postResourceSelection()).message).toBe("panel.connectFirstHint")

      const indexStore = useIndexStore()
      const settingsStore = useSettingsStore()
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      store.resource = null
      indexStore.Connected = true
      settingsStore.settings.panel.lastConnectedDevice = savedAdbDevice
      expect((await store.postResourceSelection()).message).toBe("panel.selectResource")

      store.resource = "res1"
      vi.mocked(api.postResource).mockResolvedValue({ success: true, message: "ok" })
      expect((await store.postResourceSelection()).success).toBe(true)
      expect(api.postResource).toHaveBeenCalledWith("res1")
    })
  })

  describe("init and cleanup", () => {
    it("init sets up timer and watchers, double init is no-op, cleanup resets", async () => {
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

      store.cleanup()
      expect(store.deviceStatePollTimer).toBeNull()
      expect(store.initialized).toBe(false)
      setIntervalSpy.mockRestore()
    })
  })
})
