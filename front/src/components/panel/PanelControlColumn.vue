<template>
  <PanelConnectionTabs
    :selected-controller="selectedController"
    :selected-device-key="selectedDeviceKey"
    :play-cover-address="playCoverAddress"
    :controller-options="controllerOptions"
    :device-options="deviceOptions"
    :loading="loading"
    :device-disabled="isDeviceResourceLocked"
    :resource-disabled="!selectedController || isDeviceResourceLocked"
    :selected-controller-disabled="selectedControllerDisabled"
    :is-play-cover="selectedControllerCapability?.type === 'PlayCover'"
    :resource="resource"
    :resources-list="resourcesList"
    @update:selected-controller="selectedController = $event"
    @update:selected-device-key="selectedDeviceKey = $event"
    @update:playCoverAddress="playCoverAddress = $event"
    @update:resource="resource = $event"
    @controller-change="handleControllerChange"
    @refresh-devices="refreshDevices"
  />

  <PresetSelectionCard />

  <TaskSelectionCard
    :tasks="configStore.taskList"
    :selected-task-ids="selectedTaskIds"
    :scroll-show="scrollShow"
    :controller-name="selectedControllerName"
    :resource-name="resource"
    :hide-incompatible="true"
    @update:tasks="handleTasksUpdate"
    @update:selected-tasks="handleSelectedTasksUpdate"
    @config="handleConfigTask"
    @start="StartTask"
    @stop="stopTask"
    @reset="resetConfig"
  />
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue"
import { useDialog, useMessage, type SelectGroupOption, type SelectOption } from "naive-ui"
import { useI18n } from "vue-i18n"
import PanelConnectionTabs from "@/components/panel/PanelConnectionTabs.vue"
import PresetSelectionCard from "@/components/panel/preset/PresetSelectionCard.vue"
import TaskSelectionCard from "@/components/panel/task/TaskSelectionCard.vue"
import {
  getDeviceState,
  getDevices,
  getResource,
  postDevices,
  postResource,
  startTask,
  stopTask,
  type ConnectableDevice,
  type DeviceControllerCapability,
  type DeviceControllerType,
  type PostDeviceResult,
  type PostResourceResult,
} from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { useIndexStore, useInterfaceStore, useSettingsStore, useTaskConfigStore } from "@/stores"
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
import { MOBILE_BREAKPOINT, useViewport } from "@/utils/viewport/useViewport"

const message = useMessage()
const dialog = useDialog()
const { t } = useI18n()
const configStore = useTaskConfigStore()
const indexStore = useIndexStore()
const interfaceStore = useInterfaceStore()
const settingsStore = useSettingsStore()

if (typeof window !== "undefined") {
  window.$message = message
}

const { width: viewportWidth } = useViewport()
const scrollShow = computed(() => viewportWidth.value > MOBILE_BREAKPOINT)
const isMobileView = computed(() => viewportWidth.value < MOBILE_BREAKPOINT)
const selectedController = ref<string | null>(null)
const selectedDeviceKey = ref<string | null>(null)
const availableDevices = ref<ConnectableDevice[]>([])
const controllerCapabilities = ref<DeviceControllerCapability[]>([])
const playCoverAddress = ref("")
const resource = ref<string | null>(null)
const resourcesList = ref<Array<{ label: string; value: string }>>([])
const loading = ref(false)
const isDeviceResourceLocked = ref(false)
const connectedControllerName = ref<string | null>(null)
const connectedResourceName = ref<string | null>(null)
let deviceStatePollTimer: number | null = null

const selectedTaskIds = computed(() =>
  configStore.taskList.filter((task) => task.checked).map((task) => task.id),
)

const controllerOptions = computed(() =>
  controllerCapabilities.value.map((item) => ({
    label: item.display_label,
    value: item.display_label,
    disabled: !item.enabled,
  })),
)

const selectedControllerCapability = computed(() => {
  if (!selectedController.value) {
    return null
  }
  return (
    controllerCapabilities.value.find((item) => item.display_label === selectedController.value) ||
    null
  )
})

const selectedControllerDisabled = computed(() =>
  selectedControllerCapability.value ? !selectedControllerCapability.value.enabled : false,
)

const selectedControllerName = computed(() => selectedControllerCapability.value?.name || null)

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

const deviceOptions = computed<Array<SelectOption | SelectGroupOption>>(() => {
  const capability = selectedControllerCapability.value
  const discoveredOptions = availableDevices.value.map((item) => ({
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

  const options: Array<SelectOption | SelectGroupOption> = []
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
})

const selectedDevice = computed<ConnectableDevice | null>(() => {
  if (!selectedDeviceKey.value) {
    return null
  }
  const discovered = availableDevices.value.find(
    (item) => buildDeviceFingerprint(item) === selectedDeviceKey.value,
  )
  if (discovered) {
    return discovered
  }
  const recent = (settingsStore.settings.panel.recentDevices ?? []).find(
    (item) => item.fingerprint === selectedDeviceKey.value,
  )
  if (recent) {
    return buildConnectableDeviceFromStored(recent)
  }
  // Handle custom-typed address (not in discovered or recent list)
  const capability = selectedControllerCapability.value
  if (!capability) {
    return null
  }
  return buildDeviceFromAddress(selectedDeviceKey.value, capability.type)
})

const currentSelectionFingerprint = computed(() => {
  if (selectedControllerCapability.value?.type === "PlayCover") {
    const address = playCoverAddress.value.trim()
    return address ? `playcover|${address}|` : ""
  }
  return selectedDevice.value ? buildDeviceFingerprint(selectedDevice.value) : ""
})

const isCurrentSelectionConnected = computed(() => {
  const savedDevice = settingsStore.settings.panel.lastConnectedDevice
  const selectedCapability = selectedControllerCapability.value
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
  return getStoredDeviceFingerprint(savedDevice) === currentSelectionFingerprint.value
})

function handleTasksUpdate(tasks: TaskListItem[]) {
  configStore.taskList = tasks
}

function handleSelectedTasksUpdate(selectedIds: string[]) {
  configStore.taskList = configStore.taskList.map((task) => ({
    ...task,
    checked: selectedIds.includes(task.id),
  }))
}

function handleConfigTask(taskId: string) {
  indexStore.SelectTask(taskId)
  if (isMobileView.value) {
    indexStore.openTaskSettingsDrawer(taskId)
  }
}

function saveTaskConfig() {
  if (configStore.configLoaded) {
    configStore.debouncedSave()
  }
}

watch(
  () => configStore.taskList.length,
  (length) => {
    if (length > 0) {
      indexStore.SelectTask(configStore.taskList[0]!.id)
    }
  },
  { immediate: true },
)

watch(() => configStore.taskList, saveTaskConfig, { deep: true })
watch(() => configStore.options, saveTaskConfig, { deep: true })
watch(() => configStore.preTasks, saveTaskConfig, { deep: true })
watch(() => configStore.selectedPresetName, saveTaskConfig)

async function persistLastConnectedDevice(deviceInfo: ConnectableDevice, controllerName: string) {
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
}

async function persistLastResource(name: string) {
  await settingsStore.updateSetting("panel", "lastResource", name)
}

function restoreLastConnectedDevice() {
  const savedDevice = settingsStore.settings.panel.lastConnectedDevice
  const selectedCapability = selectedControllerCapability.value
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
    playCoverAddress.value =
      savedDevice.address || getPlayCoverDefaultAddress(controllerCapabilities.value)
    return
  }

  const targetFingerprint = getStoredDeviceFingerprint(savedDevice)
  const matchedDevice = availableDevices.value.find(
    (item) => buildDeviceFingerprint(item) === targetFingerprint,
  )
  selectedDeviceKey.value = matchedDevice ? buildDeviceFingerprint(matchedDevice) : null
}

function applyDeviceRuntimeState(state: Awaited<ReturnType<typeof getDeviceState>>) {
  indexStore.setConnected(state.connected)
  isDeviceResourceLocked.value = state.connected ? state.configuration_locked : false
  connectedControllerName.value = state.controller_name
  connectedResourceName.value = state.resource_name
}

async function syncDeviceRuntimeState() {
  try {
    const state = await getDeviceState()
    applyDeviceRuntimeState(state)
  } catch {
    // 轮询失败时保持当前 UI 状态
  }
}

async function fetchDevices(controllerName?: string, restoreStored = false) {
  loading.value = true
  try {
    const data = await getDevices(controllerName)
    controllerCapabilities.value = data.controllers
    const selectedCapability = data.controllers.find(
      (item) => item.name === data.selected_controller,
    )
    selectedController.value = selectedCapability?.display_label || null

    if (!selectedCapability) {
      availableDevices.value = []
      selectedDeviceKey.value = null
      return
    }

    if (selectedCapability.type === "PlayCover") {
      availableDevices.value = []
      selectedDeviceKey.value = null
      if (restoreStored) {
        restoreLastConnectedDevice()
      }
      if (!playCoverAddress.value) {
        playCoverAddress.value = getPlayCoverDefaultAddress(data.controllers)
      }
      return
    }

    availableDevices.value = data.devices
    if (restoreStored) {
      restoreLastConnectedDevice()
    }
  } finally {
    loading.value = false
  }
}

function handleControllerChange() {
  if (isDeviceResourceLocked.value) {
    return
  }
  selectedDeviceKey.value = null
  resource.value = null
  resourcesList.value = []
  const capability = controllerCapabilities.value.find(
    (item) => item.display_label === selectedController.value,
  )
  if (capability?.type === "PlayCover" && !playCoverAddress.value) {
    playCoverAddress.value = getPlayCoverDefaultAddress(controllerCapabilities.value)
  }
  void fetchDevices(capability?.name)
  void getResourceList()
}

function refreshDevices() {
  if (
    isDeviceResourceLocked.value ||
    !selectedControllerCapability.value ||
    selectedControllerCapability.value.type === "PlayCover"
  ) {
    return
  }
  void fetchDevices(selectedControllerCapability.value.name)
}

async function connectDevices(): Promise<PostDeviceResult> {
  if (isDeviceResourceLocked.value) {
    return { success: false, message: "设备与资源已锁定，无法切换" }
  }
  const selectedCapability = selectedControllerCapability.value
  if (!selectedCapability || selectedControllerDisabled.value) {
    return { success: false, message: t("panel.selectDeviceType") }
  }

  let currentDevice: ConnectableDevice | null = null
  if (selectedCapability.type === "PlayCover") {
    const address = playCoverAddress.value.trim()
    if (!address) {
      return { success: false, message: t("panel.playcoverAddress") }
    }
    const regex = /^((25[0-5]|(2[0-4]|1\d|[1-9]|)\d)\.?\b){4}:\d{1,5}$/
    if (!regex.test(address)) {
      return { success: false, message: t("panel.invalidPlaycoverAddress") }
    }
    currentDevice = { type: "PlayCover", address }
  } else {
    currentDevice = selectedDevice.value
  }

  if (!currentDevice) {
    return { success: false, message: t("panel.selectDevice") }
  }

  const result = await postDevices({
    controller_name: selectedCapability.name,
    device: currentDevice,
  })
  indexStore.setConnected(result.success)
  if (result.success) {
    const storedDevice = await persistLastConnectedDevice(currentDevice, selectedCapability.name)
    if (storedDevice) {
      await settingsStore.addRecentDevice(storedDevice)
    }
    await getResourceList()
    await syncDeviceRuntimeState()
  }
  return result
}

async function getResourceList() {
  if (isDeviceResourceLocked.value || !selectedControllerCapability.value) {
    return
  }

  resourcesList.value = []
  loading.value = true
  try {
    const resourceData = await getResource(selectedControllerCapability.value.type)
    resourcesList.value = resourceData.map((item) => ({ label: item.name, value: item.name }))
    const savedResource = settingsStore.settings.panel.lastResource
    if (savedResource && resourceData.some((item) => item.name === savedResource)) {
      resource.value = savedResource
    }
  } finally {
    loading.value = false
  }
}

async function postResourceSelection(): Promise<PostResourceResult> {
  if (isDeviceResourceLocked.value) {
    return { success: false, message: "设备与资源已锁定，无法切换" }
  }
  if (!isCurrentSelectionConnected.value) {
    return { success: false, message: t("panel.connectFirstHint") }
  }
  if (!resource.value) {
    return { success: false, message: t("panel.selectResource") }
  }

  const result = await postResource(resource.value)
  if (result.success) {
    await persistLastResource(resource.value)
    await syncDeviceRuntimeState()
  }
  return result
}

watch(
  () => indexStore.Connected,
  (connected) => {
    if (!connected) {
      isDeviceResourceLocked.value = false
    }
  },
)

onMounted(async () => {
  await syncDeviceRuntimeState()
  if (!settingsStore.initialized) {
    await settingsStore.fetchSettings()
  }

  const savedDevice = settingsStore.settings.panel.lastConnectedDevice
  await fetchDevices(savedDevice?.controller_name, true)
  void getResourceList()

  deviceStatePollTimer = window.setInterval(() => {
    if (!indexStore.Connected && !isDeviceResourceLocked.value) {
      return
    }
    void syncDeviceRuntimeState()
  }, 3000)
})

onUnmounted(() => {
  if (deviceStatePollTimer !== null) {
    window.clearInterval(deviceStatePollTimer)
    deviceStatePollTimer = null
  }
})

async function StartTask() {
  await syncDeviceRuntimeState()

  const alreadyConnected =
    indexStore.Connected &&
    isDeviceResourceLocked.value &&
    connectedControllerName.value === selectedControllerName.value &&
    connectedResourceName.value === resource.value

  if (!alreadyConnected) {
    const connectResult = await connectDevices()
    if (!connectResult.success) {
      showGlobalMessage("error", "设备连接失败: " + connectResult.message)
      return
    }

    const resourceResult = await postResourceSelection()
    if (!resourceResult.success) {
      showGlobalMessage("error", "资源设置失败: " + resourceResult.message)
      return
    }
  }

  const isTaskCompatibleInCurrentContext = (taskId: string) =>
    interfaceStore.isTaskCompatibleByEntry(taskId, selectedControllerName.value, resource.value)

  const allCompatibleTaskIds = configStore.taskList
    .map((task) => task.id)
    .filter((taskId) => isTaskCompatibleInCurrentContext(taskId))

  const compatibleTaskIds = selectedTaskIds.value.filter((taskId) =>
    isTaskCompatibleInCurrentContext(taskId),
  )

  if (compatibleTaskIds.length === 0) {
    if (allCompatibleTaskIds.length === 0) {
      showGlobalMessage("error", t("panel.noCompatibleTask"))
    } else {
      showGlobalMessage("error", t("panel.selectTask"))
    }
    return
  }

  const payload = configStore.buildExecutionPayload(compatibleTaskIds)
  startTask(payload)
}

function resetConfig() {
  dialog.warning({
    title: t("panel.resetConfig"),
    content: t("panel.resetConfigConfirm"),
    positiveText: t("common.confirm"),
    negativeText: t("common.cancel"),
    onPositiveClick: async () => {
      await configStore.resetConfig()
      message.success(t("panel.configReset"))
    },
  })
}
</script>
