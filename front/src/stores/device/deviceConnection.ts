import { defineStore } from "pinia"
import { watch } from "vue"
import i18n from "@/app/i18n"
import { tryCatch } from "@/utils/tryCatch"
import {
  getDeviceState,
  getDevices,
  getResource,
  postCustomDevice,
  postDevices,
  postResource,
  startTask,
  stopTask,
  type ConnectableDevice,
  type DeviceControllerCapability,
  type PostDeviceResult,
  type PostResourceResult,
} from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { useIndexStore } from "@/stores/panel/session"
import { useInterfaceStore } from "@/stores/interface/interface"
import { useSettingsStore } from "@/stores/settings/settings"
import { useTaskConfigStore } from "@/stores/task-config/taskConfig"
import type { ManualStartPayload, StartConflict } from "@/types/schedulerModel"
import type { TaskListItem } from "@/types/taskConfigModel"
import type { PanelLastConnectedDevice } from "@/types/settingsModel"
import {
  buildDeviceFingerprint,
  buildDeviceLabel,
  findDeviceByIdentityOrFingerprint,
  getDeviceIdentity,
  getPlayCoverDefaultAddress,
  getStoredDeviceFingerprint,
  getStoredDeviceIdentity,
  isAdbDevice,
  isGamepadDevice,
  isWin32Device,
  storedDeviceMatchesController,
} from "@/utils/panel/device"

let watcherStopHandles: (() => void)[] = []

export const useDeviceConnectionStore = defineStore("deviceConnection", {
  state: (): {
    selectedController: string | null
    selectedDeviceKey: string | null
    availableDevices: ConnectableDevice[]
    controllerCapabilities: DeviceControllerCapability[]
    playCoverAddress: string
    resource: string | null
    resourcesList: Array<{ label: string; value: string }>
    loading: boolean
    isDeviceResourceLocked: boolean
    connectedControllerName: string | null
    connectedResourceName: string | null
    deviceStatePollTimer: number | null
    initialized: boolean
    startConflict: StartConflict | null
    _fetchDevicesRequestId: number
    _fetchResourcesRequestId: number
  } => ({
    selectedController: null,
    selectedDeviceKey: null,
    availableDevices: [],
    controllerCapabilities: [],
    playCoverAddress: "",
    resource: null,
    resourcesList: [],
    loading: false,
    isDeviceResourceLocked: false,
    connectedControllerName: null,
    connectedResourceName: null,
    deviceStatePollTimer: null,
    initialized: false,
    startConflict: null,
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

    // Backend owns scan+custom merge; Home options are flat availableDevices only.
    // recentDevices remain in settings for scheduler/other consumers.
    deviceOptions(): Array<{ label: string; value: string; disabled?: boolean }> {
      const t = i18n.global.t
      if (this.availableDevices.length === 0) {
        return [{ label: t("panel.noDevice"), value: "none-device", disabled: true }]
      }
      return this.availableDevices.map((item) => ({
        label: buildDeviceLabel(item),
        value: buildDeviceFingerprint(item),
      }))
    },

    selectedDevice(): ConnectableDevice | null {
      if (!this.selectedDeviceKey) {
        return null
      }

      const byFingerprint = this.availableDevices.find(
        (item) => buildDeviceFingerprint(item) === this.selectedDeviceKey,
      )
      if (byFingerprint) {
        return byFingerprint
      }

      // Identity match only when selectedDeviceKey is a pure identity (not a fingerprint).
      // Fingerprints contain "|"; never treat them as addresses.
      if (!this.selectedDeviceKey.includes("|")) {
        const byIdentity = this.availableDevices.find(
          (item) => getDeviceIdentity(item) === this.selectedDeviceKey,
        )
        if (byIdentity) {
          return byIdentity
        }
      }

      return null
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
      if (!storedDeviceMatchesController(savedDevice, selectedCapability)) {
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
      const storedDevice = buildStoredLastConnectedDevice(deviceInfo, controllerName)

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
      if (!storedDeviceMatchesController(savedDevice, selectedCapability)) {
        return
      }

      if (selectedCapability.type === "PlayCover") {
        this.playCoverAddress =
          savedDevice.address || getPlayCoverDefaultAddress(this.controllerCapabilities)
        return
      }

      this.selectRestoredDevice(savedDevice)
    },

    /** Fingerprint match first; identity fallback when scan returns a richer device. */
    selectRestoredDevice(savedDevice: PanelLastConnectedDevice) {
      const targetFingerprint = getStoredDeviceFingerprint(savedDevice)
      const matchedDevice = this.availableDevices.find(
        (item) => buildDeviceFingerprint(item) === targetFingerprint,
      )
      if (matchedDevice) {
        this.selectedDeviceKey = buildDeviceFingerprint(matchedDevice)
        return
      }

      const targetIdentity = getStoredDeviceIdentity(savedDevice)
      const byIdentity = this.availableDevices.find(
        (item) => getDeviceIdentity(item) === targetIdentity,
      )
      this.selectedDeviceKey = byIdentity ? buildDeviceFingerprint(byIdentity) : null
    },

    /** When locked, backend controller_name/resource_name are authority. */
    hydrateLockedSelection(
      controllerName: string | null | undefined,
      resourceName: string | null | undefined,
    ) {
      if (!this.isDeviceResourceLocked) {
        return
      }
      if (controllerName) {
        const capability = this.controllerCapabilities.find((item) => item.name === controllerName)
        if (capability) {
          this.selectedController = capability.display_label
        }
      }
      if (resourceName != null) {
        this.resource = resourceName
      }
    },

    applyDeviceRuntimeState(state: Awaited<ReturnType<typeof getDeviceState>>) {
      const indexStore = useIndexStore()
      indexStore.setConnected(state.connected)
      this.isDeviceResourceLocked = state.connected ? state.configuration_locked : false
      this.connectedControllerName = state.controller_name
      this.connectedResourceName = state.resource_name

      // When locked, always apply backend controller/resource as authority
      this.hydrateLockedSelection(state.controller_name, state.resource_name)
    },

    async syncDeviceRuntimeState() {
      const [state] = await tryCatch(() => getDeviceState())
      if (state) {
        this.applyDeviceRuntimeState(state)
      }
    },

    applyControllerData(data: Awaited<ReturnType<typeof getDevices>>) {
      this.controllerCapabilities = data.controllers
      const selectedCapability = data.controllers.find(
        (item) => item.name === data.selected_controller,
      )
      this.selectedController = selectedCapability?.display_label || null
      return selectedCapability
    },

    applyDeviceData(
      selectedCapability: DeviceControllerCapability,
      data: Awaited<ReturnType<typeof getDevices>>,
      restoreStored: boolean,
    ) {
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

      const previousKey = this.selectedDeviceKey
      const previousDevice = previousKey
        ? this.availableDevices.find((item) => buildDeviceFingerprint(item) === previousKey)
        : null
      const previousIdentity = previousDevice ? getDeviceIdentity(previousDevice) : null

      this.availableDevices = data.devices
      if (restoreStored) {
        this.restoreLastConnectedDevice()
        return
      }
      this.rebindSelectedDeviceKey(previousKey, previousIdentity)
    },

    /**
     * After availableDevices is replaced, keep selection if fingerprint still exists;
     * otherwise rebind by semantic identity; otherwise clear (never treat fingerprints as addresses).
     */
    rebindSelectedDeviceKey(previousKey: string | null, previousIdentity: string | null) {
      if (!previousKey) {
        this.selectedDeviceKey = null
        return
      }

      const byFingerprint = this.availableDevices.find(
        (item) => buildDeviceFingerprint(item) === previousKey,
      )
      if (byFingerprint) {
        this.selectedDeviceKey = buildDeviceFingerprint(byFingerprint)
        return
      }

      if (previousIdentity) {
        const byIdentity = this.availableDevices.find(
          (item) => getDeviceIdentity(item) === previousIdentity,
        )
        if (byIdentity) {
          this.selectedDeviceKey = buildDeviceFingerprint(byIdentity)
          return
        }
      }

      this.selectedDeviceKey = null
    },

    resetDeviceLoading(requestId: number) {
      if (requestId === this._fetchDevicesRequestId) {
        this.loading = false
      }
    },

    async fetchDevices(controllerName?: string, restoreStored = false) {
      const requestId = ++this._fetchDevicesRequestId
      this.loading = true

      const [data] = await tryCatch(() => getDevices(controllerName))
      if (!data || requestId !== this._fetchDevicesRequestId) {
        this.resetDeviceLoading(requestId)
        return false
      }

      const selectedCapability = this.applyControllerData(data)
      if (!selectedCapability) {
        this.availableDevices = []
        this.selectedDeviceKey = null
        this.resetDeviceLoading(requestId)
        return true
      }

      this.applyDeviceData(selectedCapability, data, restoreStored)

      // After capabilities load, re-apply locked runtime selection as authority
      if (this.isDeviceResourceLocked && this.connectedControllerName) {
        this.hydrateLockedSelection(this.connectedControllerName, this.connectedResourceName)
      }

      this.resetDeviceLoading(requestId)
      return true
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

      void this.fetchDevices(capability?.name).then((ok) => {
        if (ok) return this.getResourceList()
      })
    },

    openDevices() {
      if (
        this.isDeviceResourceLocked ||
        !this.selectedControllerCapability ||
        this.selectedControllerCapability.type === "PlayCover"
      ) {
        return
      }
      void this.fetchDevices(this.selectedControllerCapability.name)
    },

    isStillOnController(controllerName: string, displayLabel: string): boolean {
      return (
        this.selectedControllerCapability?.name === controllerName ||
        this.selectedController === displayLabel
      )
    },

    handleCustomDeviceSaveFailure(previousKey: string | null, message?: string) {
      // Preserve previous selection on save failure
      this.selectedDeviceKey = previousKey
      showGlobalMessage("error", message || "保存自定义设备失败")
    },

    async selectPersistedCustomDevice(
      persisted: ConnectableDevice,
      controllerName: string,
      displayLabel: string,
    ) {
      const applied = await this.fetchDevices(controllerName)
      // Stale GET discarded by request-id — do not reselect on old controller
      if (!applied) {
        return
      }
      if (!this.isStillOnController(controllerName, displayLabel)) {
        return
      }

      const matched = findDeviceByIdentityOrFingerprint(this.availableDevices, persisted)
      if (matched) {
        this.selectedDeviceKey = buildDeviceFingerprint(matched)
        return
      }

      // Do not append client-only fallback — backend list is source of truth
      showGlobalMessage("error", "自定义设备已保存，但刷新列表后未找到该设备")
    },

    async createCustomDevice(rawAddress: string) {
      if (this.isDeviceResourceLocked) {
        return
      }
      const capability = this.selectedControllerCapability
      if (!capability || capability.type === "PlayCover") {
        return
      }

      const address = rawAddress.trim()
      if (!address) {
        return
      }

      const controllerName = capability.name
      const displayLabel = capability.display_label
      const previousKey = this.selectedDeviceKey

      const [result] = await tryCatch(() =>
        postCustomDevice({
          controller_name: controllerName,
          type: capability.type,
          address,
        }),
      )

      // Still on the same controller after POST? (user may have switched meanwhile)
      if (!this.isStillOnController(controllerName, displayLabel)) {
        return
      }

      if (!result?.success || !result.data) {
        this.handleCustomDeviceSaveFailure(previousKey, result?.message)
        return
      }

      await this.selectPersistedCustomDevice(result.data, controllerName, displayLabel)
    },

    buildPlayCoverDevice(): { device: ConnectableDevice } | { error: string } {
      const t = i18n.global.t
      const address = this.playCoverAddress.trim()
      if (!address) {
        return { error: t("panel.playcoverAddress") }
      }
      const regex = /^((25[0-5]|(2[0-4]|1\d|[1-9]|)\d)\.?\b){4}:\d{1,5}$/
      if (!regex.test(address)) {
        return { error: t("panel.invalidPlaycoverAddress") }
      }
      return { device: { type: "PlayCover", address } }
    },

    async connectDevices(): Promise<PostDeviceResult> {
      const t = i18n.global.t

      if (this.isDeviceResourceLocked) {
        return { success: false, message: "设备与资源已锁定，无法切换" }
      }

      const selectedCapability = this.selectedControllerCapability
      if (!selectedCapability || this.selectedControllerDisabled) {
        return { success: false, message: t("panel.selectDeviceType") }
      }

      let currentDevice: ConnectableDevice | null = null
      if (selectedCapability.type === "PlayCover") {
        const playCoverResult = this.buildPlayCoverDevice()
        if ("error" in playCoverResult) {
          return { success: false, message: playCoverResult.error }
        }
        currentDevice = playCoverResult.device
      }

      if (!currentDevice) {
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

    resetResourceLoading(requestId: number) {
      if (requestId === this._fetchResourcesRequestId) {
        this.loading = false
      }
    },

    async getResourceList() {
      if (this.isDeviceResourceLocked || !this.selectedControllerCapability) {
        return
      }

      const requestId = ++this._fetchResourcesRequestId
      const settingsStore = useSettingsStore()
      this.resourcesList = []
      this.loading = true

      const capability = this.selectedControllerCapability
      if (!capability) {
        this.resetResourceLoading(requestId)
        return
      }

      const [resourceData] = await tryCatch(() => getResource(capability.type))
      if (!resourceData || requestId !== this._fetchResourcesRequestId) {
        this.resetResourceLoading(requestId)
        return
      }

      this.resourcesList = resourceData.map((item) => ({ label: item.name, value: item.name }))
      const savedResource = settingsStore.settings.panel.lastResource
      if (savedResource && resourceData.some((item) => item.name === savedResource)) {
        this.resource = savedResource
      }
      this.resetResourceLoading(requestId)
    },

    async postResourceSelection(): Promise<PostResourceResult> {
      const t = i18n.global.t

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

    clearStartConflict() {
      this.startConflict = null
    },

    async stopActiveAndRestart(): Promise<boolean> {
      const stopped = await stopTask()
      if (!stopped) {
        return false
      }
      this.clearStartConflict()
      return this.StartTask()
    },

    resolveStartDevice(): { ok: true; device: ConnectableDevice } | { ok: false; message: string } {
      const t = i18n.global.t
      const selectedCapability = this.selectedControllerCapability
      if (!selectedCapability || this.selectedControllerDisabled) {
        return { ok: false, message: t("panel.selectDeviceType") }
      }

      if (selectedCapability.type === "PlayCover") {
        const playCoverResult = this.buildPlayCoverDevice()
        if ("error" in playCoverResult) {
          return { ok: false, message: playCoverResult.error }
        }
        return { ok: true, device: playCoverResult.device }
      }

      if (!this.selectedDevice) {
        return { ok: false, message: t("panel.selectDevice") }
      }
      return { ok: true, device: this.selectedDevice }
    },

    async StartTask(): Promise<boolean> {
      const t = i18n.global.t
      const interfaceStore = useInterfaceStore()
      const configStore = useTaskConfigStore()

      await this.syncDeviceRuntimeState()

      const selectedCapability = this.selectedControllerCapability
      if (!selectedCapability || this.selectedControllerDisabled) {
        showGlobalMessage("error", t("panel.selectDeviceType"))
        return false
      }

      const deviceResult = this.resolveStartDevice()
      if (!deviceResult.ok) {
        showGlobalMessage("error", deviceResult.message)
        return false
      }

      if (!this.resource) {
        showGlobalMessage("error", t("panel.selectResource"))
        return false
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
          return false
        }
        showGlobalMessage("error", t("panel.selectTask"))
        return false
      }

      const execution = configStore.buildExecutionPayload(compatibleTaskIds)
      const payload: ManualStartPayload = {
        task_list: execution.task_list,
        task_options: execution.task_options,
        preTasks: execution.preTasks,
        controller_name: selectedCapability.name,
        device: {
          controller_name: selectedCapability.name,
          device_type: selectedCapability.type,
          device_address: getDeviceIdentity(deviceResult.device),
        },
        resource_name: this.resource,
      }

      const result = await startTask(payload)
      if (result.accepted) {
        this.startConflict = null
        return true
      }
      if (result.conflict) {
        this.startConflict = result.conflict
        return false
      }
      return false
    },

    resetConfig() {
      const t = i18n.global.t
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

      const fetchSavedDevice = () => {
        const savedDevice = settingsStore.settings.panel.lastConnectedDevice
        void this.fetchDevices(savedDevice?.controller_name, true).then((ok) => {
          if (ok) return this.getResourceList()
        })
      }

      // Fetch settings if not initialized
      const settingsPromise = settingsStore.initialized
        ? Promise.resolve()
        : settingsStore.fetchSettings()
      void settingsPromise.then(() => fetchSavedDevice())

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
            indexStore.SelectTask(configStore.taskList[0].id)
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

// --- Helper functions used by the store ---

function buildStoredLastConnectedDevice(
  deviceInfo: ConnectableDevice,
  controllerName: string,
): PanelLastConnectedDevice {
  if (isAdbDevice(deviceInfo)) {
    return {
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
  }
  if (isWin32Device(deviceInfo)) {
    return {
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
  }
  if (isGamepadDevice(deviceInfo)) {
    return {
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
  }
  return {
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
