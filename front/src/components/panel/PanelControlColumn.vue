<template>
  <PanelConnectionTabs
    :selected-controller="selectedController"
    :selected-device-key="selectedDeviceKey"
    :play-cover-address="playCoverAddress"
    :controller-options="controllerOptions"
    :device-options="deviceOptions"
    :loading="loading"
    :device-disabled="isDeviceResourceLocked"
    :resource-disabled="!isCurrentSelectionConnected || isDeviceResourceLocked"
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
    @connect-devices="connectDevices"
    @fetch-resources="getResourceList"
    @confirm-resource="postResourceSelection"
  />

  <PresetSelectionCard />

  <TaskSelectionCard
    :tasks="configStore.taskList"
    :selected-task-ids="selectedTaskIds"
    :scroll-show="scrollShow"
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
import { useDialog, useMessage } from "naive-ui"
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
} from "@/services/api"
import { useIndexStore, useSettingsStore, useTaskConfigStore } from "@/stores"
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

const deviceOptions = computed(() => {
  if (availableDevices.value.length === 0) {
    return [{ label: t("panel.noDevice"), value: "none-device", disabled: true }]
  }
  return availableDevices.value.map((item) => ({
    label: buildDeviceLabel(item),
    value: buildDeviceFingerprint(item),
  }))
})

const selectedDevice = computed(() => {
  if (!selectedDeviceKey.value) {
    return null
  }
  return (
    availableDevices.value.find(
      (item) => buildDeviceFingerprint(item) === selectedDeviceKey.value,
    ) || null
  )
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
  const capability = controllerCapabilities.value.find(
    (item) => item.display_label === selectedController.value,
  )
  if (capability?.type === "PlayCover" && !playCoverAddress.value) {
    playCoverAddress.value = getPlayCoverDefaultAddress(controllerCapabilities.value)
  }
  void fetchDevices(capability?.name)
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

async function connectDevices() {
  if (isDeviceResourceLocked.value) {
    return
  }
  const selectedCapability = selectedControllerCapability.value
  if (!selectedCapability || selectedControllerDisabled.value) {
    message.error(t("panel.selectDeviceType"))
    return
  }

  let currentDevice: ConnectableDevice | null = null
  if (selectedCapability.type === "PlayCover") {
    const address = playCoverAddress.value.trim()
    if (!address) {
      message.error(t("panel.playcoverAddress"))
      return
    }
    const regex = /^((25[0-5]|(2[0-4]|1\d|[1-9]|)\d)\.?\b){4}:\d{1,5}$/
    if (!regex.test(address)) {
      message.error(t("panel.invalidPlaycoverAddress"))
      return
    }
    currentDevice = { type: "PlayCover", address }
  } else {
    currentDevice = selectedDevice.value
  }

  if (!currentDevice) {
    message.error(t("panel.selectDevice"))
    return
  }

  const success = await postDevices({
    controller_name: selectedCapability.name,
    device: currentDevice,
  })
  indexStore.setConnected(success)
  if (success) {
    await persistLastConnectedDevice(currentDevice, selectedCapability.name)
    await getResourceList()
    await syncDeviceRuntimeState()
  }
}

async function getResourceList() {
  if (isDeviceResourceLocked.value || !isCurrentSelectionConnected.value) {
    return
  }

  resourcesList.value = []
  loading.value = true
  try {
    const resourceData = await getResource()
    resourcesList.value = resourceData.map((item) => ({ label: item, value: item }))
    const savedResource = settingsStore.settings.panel.lastResource
    if (savedResource && resourceData.includes(savedResource)) {
      resource.value = savedResource
    }
  } finally {
    loading.value = false
  }
}

async function postResourceSelection() {
  if (isDeviceResourceLocked.value) {
    return
  }
  if (!isCurrentSelectionConnected.value) {
    message.error(t("panel.connectFirstHint"))
    return
  }
  if (!resource.value) {
    message.error(t("panel.selectResource"))
    return
  }

  const success = await postResource(resource.value)
  if (success) {
    await persistLastResource(resource.value)
    await syncDeviceRuntimeState()
  }
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

function StartTask() {
  const payload = configStore.buildExecutionPayload(selectedTaskIds.value)
  if (payload.task_list.length === 0) {
    message.error(t("panel.selectTask"))
    return
  }
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
