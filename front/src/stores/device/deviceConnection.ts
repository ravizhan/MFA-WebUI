import { defineStore } from "pinia"
import { watch } from "vue"
import { useI18n } from "vue-i18n"
import {
  getDeviceState,
  getDevices,
  getResource,
  postDevices,
  postResource,
  startTask,
  type ConnectableDevice,
  type DeviceControllerCapability,
  type DeviceControllerType,
  type PostDeviceResult,
  type PostResourceResult,
} from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { useIndexStore } from "@/stores/panel/session"
import { useInterfaceStore } from "@/stores/interface/interface"
import { useSettingsStore } from "@/stores/settings/settings"
import { useTaskConfigStore } from "@/stores/task-config/taskConfig"
import type { TaskListItem } from "@/types/task-config/model"
import type { PanelLastConnectedDevice } from "@/types/settings/model"
import {
  buildDeviceFingerprint,
  buildDeviceLabel,
  getPlayCoverDefaultAddress,
  getStoredDeviceFingerprint,
  isAdbDevice,
  isGamepadDevice,
  isWin32Device,
} from "@/utils/panel/device"

let watcherStopHandles: (() => void)[] = []

export const useDeviceConnectionStore = defineStore("deviceConnection", {
  state: () => ({
    selectedController: null as string | null,
    selectedDeviceKey: null as string | null,
    availableDevices: [] as ConnectableDevice[],
    controllerCapabilities: [] as DeviceControllerCapability[],
    playCoverAddress: "",
    resource: null as string | null,
    resourcesList: [] as Array<{ label: string; value: string }>,
    loading: false,
    isDeviceResourceLocked: false,
    connectedControllerName: null as string | null,
    connectedResourceName: null as string | null,
    deviceStatePollTimer: null as number | null,
    initialized: false,
    _fetchDevicesRequestId: 0,
    _fetchResourcesRequestId: 0,
  }),

  getters: {
    controllerOptions(state) {
      return state.controllerCapabilities.map((item) => ({
        label: item.display_label,
        value: item.display_label,
        disabled: !item.enabled,
      }))
    },

    selectedControllerCapability(state): DeviceControllerCapability | null {
      if (!state.selectedController) {
        return null
      }
      return (
        state.controllerCapabilities.find(
          (item) => item.display_label === state.selectedController,
        ) || null
      )
    },

    selectedControllerDisabled(): boolean {
      return this.selectedControllerCapability ? !this.selectedControllerCapability.enabled : false
    },

    selectedControllerName(): string | null {
      return this.selectedControllerCapability?.name || null
    },

    deviceOptions(): Array<{
      label: string
      value: string
      type?: string
      key?: string
      children?: Array<{ label: string; value: string }>
    }> {
      const { t } = useI18n()
      const capability = this.selectedControllerCapability
      const settingsStore = useSettingsStore()

      const discoveredOptions = this.availableDevices.map((item) => ({
        label: buildDeviceLabel(item),
        value: buildDeviceFingerprint(item),
      }))

      const recentDevices = settingsStore.settings.panel.recentDevices ?? []
      const discoveredFingerprints = new Set(discoveredOptions.map((item) => item.value))
      const recentOptions = recentDevices
        .filter(
          (item) => item.type === capability?.type && !discoveredFingerprints.has(item.fingerprint),
        )
        .map((item) => ({
          label: buildStoredDeviceLabel(item),
          value: item.fingerprint,
        }))

      const options: Array<{
        label: string
        value: string
        type?: string
        key?: string
        children?: Array<{ label: string; value: string }>
      }> = []

      if (recentOptions.length > 0) {
        options.push({
          type: "group",
          label: t("panel.recentDevices"),
          key: "recent-devices",
          children: recentOptions,
        })
      }
      if (discoveredOptions.length > 0) {
        options.push({
          type: "group",
          label: t("panel.discoveredDevices"),
          key: "discovered-devices",
          children: discoveredOptions,
        })
      }
      if (options.length === 0) {
        return [{ label: t("panel.noDevice"), value: "none-device", disabled: true }]
      }
      return options
    },

    selectedDevice(): ConnectableDevice | null {
      if (!this.selectedDeviceKey) {
        return null
      }
      const settingsStore = useSettingsStore()

      const discovered = this.availableDevices.find(
        (item) => buildDeviceFingerprint(item) === this.selectedDeviceKey,
      )
      if (discovered) {
        return discovered
      }

      const recent = (settingsStore.settings.panel.recentDevices ?? []).find(
        (item) => item.fingerprint === this.selectedDeviceKey,
      )
      if (recent) {
        return buildConnectableDeviceFromStored(recent)
      }

      const capability = this.selectedControllerCapability
      if (!capability) {
        return null
      }
      return buildDeviceFromAddress(this.selectedDeviceKey, capability.type)
    },

    currentSelectionFingerprint(): string {
      if (this.selectedControllerCapability?.type === "PlayCover") {
        const address = this.playCoverAddress.trim()
        return address ? `playcover|${address}|` : ""
      }
      return this.selectedDevice ? buildDeviceFingerprint(this.selectedDevice) : ""
    },

    isCurrentSelectionConnected(): boolean {
      const indexStore = useIndexStore()
      const settingsStore = useSettingsStore()
      const savedDevice = settingsStore.settings.panel.lastConnectedDevice
      const selectedCapability = this.selectedControllerCapability

      if (!indexStore.Connected || !savedDevice || !selectedCapability) {
        return false
      }
      if (savedDevice.controller_name) {
        if (savedDevice.controller_name !== selectedCapability.name) {
          return false
        }
      } else if (savedDevice.type !== selectedCapability.type) {
        return false
      }
      return getStoredDeviceFingerprint(savedDevice) === this.currentSelectionFingerprint
    },

    selectedTaskIds(): string[] {
      const configStore = useTaskConfigStore()
      return configStore.taskList.filter((task) => task.checked).map((task) => task.id)
    },
  },

  actions: {
    handleTasksUpdate(tasks: TaskListItem[]) {
      const configStore = useTaskConfigStore()
      configStore.taskList = tasks
    },

    handleSelectedTasksUpdate(selectedIds: string[]) {
      const configStore = useTaskConfigStore()
      configStore.taskList = configStore.taskList.map((task) => ({
        ...task,
        checked: selectedIds.includes(task.id),
      }))
    },

    saveTaskConfig() {
      const configStore = useTaskConfigStore()
      if (configStore.configLoaded) {
        configStore.debouncedSave()
      }
    },

    async persistLastConnectedDevice(deviceInfo: ConnectableDevice, controllerName: string) {
      const settingsStore = useSettingsStore()
      let storedDevice: PanelLastConnectedDevice

      if (isAdbDevice(deviceInfo)) {
        storedDevice = {
          type: "Adb",
          controller_name: controllerName,
          fingerprint: buildDeviceFingerprint(deviceInfo),
          adb_path: deviceInfo.adb_path,
          address: deviceInfo.address,
          class_name: "",
          window_name: "",
          hWnd: 0,
          gamepad_type: 0,
          uuid: "",
        }
      } else if (isWin32Device(deviceInfo)) {
        storedDevice = {
          type: "Win32",
          controller_name: controllerName,
          fingerprint: buildDeviceFingerprint(deviceInfo),
          adb_path: "",
          address: "",
          class_name: deviceInfo.class_name,
          window_name: deviceInfo.window_name,
          hWnd: deviceInfo.hWnd,
          gamepad_type: 0,
          uuid: "",
        }
      } else if (isGamepadDevice(deviceInfo)) {
        storedDevice = {
          type: "Gamepad",
          controller_name: controllerName,
          fingerprint: buildDeviceFingerprint(deviceInfo),
          adb_path: "",
          address: "",
          class_name: deviceInfo.class_name,
          window_name: deviceInfo.window_name,
          hWnd: deviceInfo.hWnd,
          gamepad_type: deviceInfo.gamepad_type,
          uuid: "",
        }
      } else {
        storedDevice = {
          type: "PlayCover",
          controller_name: controllerName,
          fingerprint: buildDeviceFingerprint(deviceInfo),
          adb_path: "",
          address: deviceInfo.address,
          class_name: "",
          window_name: deviceInfo.name || "",
          hWnd: 0,
          gamepad_type: 0,
          uuid: deviceInfo.uuid || "",
        }
      }

      await settingsStore.updateSetting("panel", "lastConnectedDevice", storedDevice)
      return storedDevice
    },

    async persistLastResource(name: string) {
      const settingsStore = useSettingsStore()
      await settingsStore.updateSetting("panel", "lastResource", name)
    },

    restoreLastConnectedDevice() {
      const settingsStore = useSettingsStore()
      const savedDevice = settingsStore.settings.panel.lastConnectedDevice
      const selectedCapability = this.selectedControllerCapability

      if (!savedDevice || !selectedCapability) {
        return
      }
      if (savedDevice.controller_name) {
        if (savedDevice.controller_name !== selectedCapability.name) {
          return
        }
      } else if (savedDevice.type !== selectedCapability.type) {
        return
      }

      if (selectedCapability.type === "PlayCover") {
        this.playCoverAddress =
          savedDevice.address || getPlayCoverDefaultAddress(this.controllerCapabilities)
        return
      }

      const targetFingerprint = getStoredDeviceFingerprint(savedDevice)
      const matchedDevice = this.availableDevices.find(
        (item) => buildDeviceFingerprint(item) === targetFingerprint,
      )
      this.selectedDeviceKey = matchedDevice ? buildDeviceFingerprint(matchedDevice) : null
    },

    applyDeviceRuntimeState(state: Awaited<ReturnType<typeof getDeviceState>>) {
      const indexStore = useIndexStore()
      indexStore.setConnected(state.connected)
      this.isDeviceResourceLocked = state.connected ? state.configuration_locked : false
      this.connectedControllerName = state.controller_name
      this.connectedResourceName = state.resource_name

      // Hydrate selected controller and resource from runtime state when locked
      if (this.isDeviceResourceLocked) {
        if (state.controller_name && !this.selectedController) {
          const capability = this.controllerCapabilities.find(
            (item) => item.name === state.controller_name,
          )
          if (capability) {
            this.selectedController = capability.display_label
          }
        }
        if (state.resource_name && !this.resource) {
          this.resource = state.resource_name
        }
      }
    },

    async syncDeviceRuntimeState() {
      try {
        const state = await getDeviceState()
        this.applyDeviceRuntimeState(state)
      } catch {
        // Ignore polling failures to keep current UI state
      }
    },

    async fetchDevices(controllerName?: string, restoreStored = false) {
      const requestId = ++this._fetchDevicesRequestId
      this.loading = true
      try {
        const data = await getDevices(controllerName)
        if (requestId !== this._fetchDevicesRequestId) return

        this.controllerCapabilities = data.controllers
        const selectedCapability = data.controllers.find(
          (item) => item.name === data.selected_controller,
        )
        this.selectedController = selectedCapability?.display_label || null

        if (!selectedCapability) {
          this.availableDevices = []
          this.selectedDeviceKey = null
          return
        }

        if (selectedCapability.type === "PlayCover") {
          this.availableDevices = []
          this.selectedDeviceKey = null
          if (restoreStored) {
            this.restoreLastConnectedDevice()
          }
          if (!this.playCoverAddress) {
            this.playCoverAddress = getPlayCoverDefaultAddress(data.controllers)
          }
          return
        }

        this.availableDevices = data.devices
        if (restoreStored) {
          this.restoreLastConnectedDevice()
        }
      } finally {
        if (requestId === this._fetchDevicesRequestId) {
          this.loading = false
        }
      }
    },

    handleControllerChange() {
      if (this.isDeviceResourceLocked) {
        return
      }
      this.selectedDeviceKey = null
      this.resource = null
      this.resourcesList = []

      const capability = this.controllerCapabilities.find(
        (item) => item.display_label === this.selectedController,
      )
      if (capability?.type === "PlayCover" && !this.playCoverAddress) {
        this.playCoverAddress = getPlayCoverDefaultAddress(this.controllerCapabilities)
      }

      void this.fetchDevices(capability?.name)
      void this.getResourceList()
    },

    refreshDevices() {
      if (
        this.isDeviceResourceLocked ||
        !this.selectedControllerCapability ||
        this.selectedControllerCapability.type === "PlayCover"
      ) {
        return
      }
      void this.fetchDevices(this.selectedControllerCapability.name)
    },

    async connectDevices(): Promise<PostDeviceResult> {
      const { t } = useI18n()

      if (this.isDeviceResourceLocked) {
        return { success: false, message: "设备与资源已锁定，无法切换" }
      }

      const selectedCapability = this.selectedControllerCapability
      if (!selectedCapability || this.selectedControllerDisabled) {
        return { success: false, message: t("panel.selectDeviceType") }
      }

      let currentDevice: ConnectableDevice | null = null
      if (selectedCapability.type === "PlayCover") {
        const address = this.playCoverAddress.trim()
        if (!address) {
          return { success: false, message: t("panel.playcoverAddress") }
        }
        const regex = /^((25[0-5]|(2[0-4]|1\d|[1-9]|)\d)\.?\b){4}:\d{1,5}$/
        if (!regex.test(address)) {
          return { success: false, message: t("panel.invalidPlaycoverAddress") }
        }
        currentDevice = { type: "PlayCover", address }
      } else {
        currentDevice = this.selectedDevice
      }

      if (!currentDevice) {
        return { success: false, message: t("panel.selectDevice") }
      }

      const indexStore = useIndexStore()
      const settingsStore = useSettingsStore()

      const result = await postDevices({
        controller_name: selectedCapability.name,
        device: currentDevice,
      })

      indexStore.setConnected(result.success)
      if (result.success) {
        const storedDevice = await this.persistLastConnectedDevice(
          currentDevice,
          selectedCapability.name,
        )
        if (storedDevice) {
          await settingsStore.addRecentDevice(storedDevice)
        }
        await this.getResourceList()
        await this.syncDeviceRuntimeState()
      }
      return result
    },

    async getResourceList() {
      if (this.isDeviceResourceLocked || !this.selectedControllerCapability) {
        return
      }

      const requestId = ++this._fetchResourcesRequestId
      const settingsStore = useSettingsStore()
      this.resourcesList = []
      this.loading = true
      try {
        const resourceData = await getResource(this.selectedControllerCapability.type)
        if (requestId !== this._fetchResourcesRequestId) return

        this.resourcesList = resourceData.map((item) => ({ label: item.name, value: item.name }))
        const savedResource = settingsStore.settings.panel.lastResource
        if (savedResource && resourceData.some((item) => item.name === savedResource)) {
          this.resource = savedResource
        }
      } finally {
        if (requestId === this._fetchResourcesRequestId) {
          this.loading = false
        }
      }
    },

    async postResourceSelection(): Promise<PostResourceResult> {
      const { t } = useI18n()

      if (this.isDeviceResourceLocked) {
        return { success: false, message: "设备与资源已锁定，无法切换" }
      }
      if (!this.isCurrentSelectionConnected) {
        return { success: false, message: t("panel.connectFirstHint") }
      }
      if (!this.resource) {
        return { success: false, message: t("panel.selectResource") }
      }

      const result = await postResource(this.resource)
      if (result.success) {
        await this.persistLastResource(this.resource)
        await this.syncDeviceRuntimeState()
      }
      return result
    },

    async StartTask(): Promise<boolean> {
      const { t } = useI18n()
      const indexStore = useIndexStore()
      const interfaceStore = useInterfaceStore()
      const configStore = useTaskConfigStore()

      await this.syncDeviceRuntimeState()

      const alreadyConnected =
        indexStore.Connected &&
        this.isDeviceResourceLocked &&
        this.connectedControllerName === this.selectedControllerName &&
        this.connectedResourceName === this.resource

      if (!alreadyConnected) {
        const connectResult = await this.connectDevices()
        if (!connectResult.success) {
          showGlobalMessage("error", "设备连接失败: " + connectResult.message)
          return false
        }

        const resourceResult = await this.postResourceSelection()
        if (!resourceResult.success) {
          showGlobalMessage("error", "资源设置失败: " + resourceResult.message)
          return false
        }
      }

      const isTaskCompatibleInCurrentContext = (taskId: string) =>
        interfaceStore.isTaskCompatibleByEntry(taskId, this.selectedControllerName, this.resource)

      const allCompatibleTaskIds = configStore.taskList
        .map((task) => task.id)
        .filter((taskId) => isTaskCompatibleInCurrentContext(taskId))

      const compatibleTaskIds = this.selectedTaskIds.filter((taskId) =>
        isTaskCompatibleInCurrentContext(taskId),
      )

      if (compatibleTaskIds.length === 0) {
        if (allCompatibleTaskIds.length === 0) {
          showGlobalMessage("error", t("panel.noCompatibleTask"))
        } else {
          showGlobalMessage("error", t("panel.selectTask"))
        }
        return false
      }

      const payload = configStore.buildExecutionPayload(compatibleTaskIds)
      return await startTask(payload)
    },

    resetConfig() {
      const { t } = useI18n()
      const configStore = useTaskConfigStore()

      if (confirm(t("panel.resetConfigConfirm"))) {
        void configStore.resetConfig()
        showGlobalMessage("success", t("panel.configReset"))
      }
    },

    init() {
      if (this.initialized) {
        return
      }
      this.initialized = true

      const indexStore = useIndexStore()
      const configStore = useTaskConfigStore()
      const settingsStore = useSettingsStore()

      // Sync device state
      void this.syncDeviceRuntimeState()

      // Fetch settings if not initialized
      if (!settingsStore.initialized) {
        void settingsStore.fetchSettings().then(() => {
          const savedDevice = settingsStore.settings.panel.lastConnectedDevice
          void this.fetchDevices(savedDevice?.controller_name, true)
          void this.getResourceList()
        })
      } else {
        const savedDevice = settingsStore.settings.panel.lastConnectedDevice
        void this.fetchDevices(savedDevice?.controller_name, true)
        void this.getResourceList()
      }

      // Start device state poll timer
      this.deviceStatePollTimer = window.setInterval(() => {
        if (!indexStore.Connected && !this.isDeviceResourceLocked) {
          return
        }
        void this.syncDeviceRuntimeState()
      }, 3000)

      // Set up watchers
      const stop1 = watch(
        () => configStore.taskList.length,
        (length) => {
          if (length > 0) {
            indexStore.SelectTask(configStore.taskList[0]!.id)
          }
        },
        { immediate: true },
      )

      const stop2 = watch(
        () => configStore.taskList,
        () => this.saveTaskConfig(),
        { deep: true },
      )

      const stop3 = watch(
        () => configStore.options,
        () => this.saveTaskConfig(),
        { deep: true },
      )

      const stop4 = watch(
        () => configStore.preTasks,
        () => this.saveTaskConfig(),
        { deep: true },
      )

      const stop5 = watch(
        () => configStore.selectedPresetName,
        () => this.saveTaskConfig(),
      )

      const stop6 = watch(
        () => indexStore.Connected,
        (connected) => {
          if (!connected) {
            this.isDeviceResourceLocked = false
          }
        },
      )

      watcherStopHandles = [stop1, stop2, stop3, stop4, stop5, stop6]
    },

    cleanup() {
      if (this.deviceStatePollTimer !== null) {
        window.clearInterval(this.deviceStatePollTimer)
        this.deviceStatePollTimer = null
      }

      watcherStopHandles.forEach((stop) => stop())
      watcherStopHandles = []

      this.initialized = false
    },
  },
})

// --- Helper functions used by the store (replicated from PanelControlColumn) ---

function buildStoredDeviceLabel(stored: PanelLastConnectedDevice): string {
  if (stored.type === "Adb") {
    return `${stored.address} (${stored.adb_path})`
  }
  if (stored.type === "Win32" || stored.type === "Gamepad") {
    return `${stored.window_name || stored.class_name} (${stored.class_name || stored.address})`
  }
  return stored.address
}

function buildConnectableDeviceFromStored(stored: PanelLastConnectedDevice): ConnectableDevice {
  if (stored.type === "Adb") {
    return {
      type: "Adb",
      name: stored.controller_name || stored.address,
      adb_path: stored.adb_path,
      address: stored.address,
      screencap_methods: "",
      input_methods: "",
      config: {},
    }
  }
  if (stored.type === "Win32") {
    return {
      type: "Win32",
      hWnd: stored.hWnd,
      class_name: stored.class_name,
      window_name: stored.window_name,
      screencap_methods: 0,
      input_methods: 0,
    }
  }
  if (stored.type === "Gamepad") {
    return {
      type: "Gamepad",
      hWnd: stored.hWnd,
      class_name: stored.class_name,
      window_name: stored.window_name,
      screencap_methods: 0,
      gamepad_type: stored.gamepad_type,
    }
  }
  return {
    type: "PlayCover",
    address: stored.address,
    uuid: stored.uuid,
  }
}

function buildDeviceFromAddress(
  address: string,
  type: DeviceControllerType,
): ConnectableDevice | null {
  if (type === "Adb") {
    return {
      type: "Adb",
      name: address,
      adb_path: "",
      address,
      screencap_methods: "",
      input_methods: "",
      config: {},
    }
  }
  if (type === "Win32") {
    const hWnd = Number.parseInt(address, 10)
    if (Number.isNaN(hWnd)) {
      return null
    }
    return {
      type: "Win32",
      hWnd,
      class_name: "",
      window_name: "",
      screencap_methods: 0,
      input_methods: 0,
    }
  }
  if (type === "Gamepad") {
    const parts = address.split("|")
    const hWnd = Number.parseInt(parts[0] ?? "", 10)
    if (Number.isNaN(hWnd)) {
      return null
    }
    return {
      type: "Gamepad",
      hWnd,
      class_name: "",
      window_name: "",
      screencap_methods: 0,
      gamepad_type: Number.parseInt(parts[1] ?? "0", 10) || 0,
    }
  }
  return null
}
