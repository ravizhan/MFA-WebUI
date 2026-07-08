<template>
  <div class="modal" :class="{ 'modal-open': showDialog }" @click.self="handleCancel">
    <div class="modal-box max-w-3xl max-h-[90vh] overflow-y-auto">
      <h3 class="font-bold text-lg mb-4">
        {{
          isEditMode
            ? t("settings.scheduler.dialog.editTitle")
            : t("settings.scheduler.dialog.createTitle")
        }}
      </h3>

      <div class="space-y-4">
        <!-- Name -->
        <div class="form-control">
          <label class="label">
            <span class="label-text">{{ t("settings.scheduler.dialog.taskName") }}</span>
          </label>
          <input
            v-model="formData.name"
            type="text"
            class="input input-bordered"
            :placeholder="t('settings.scheduler.dialog.taskNamePlaceholder')"
          />
        </div>

        <!-- Description -->
        <div class="form-control">
          <label class="label">
            <span class="label-text">{{ t("settings.scheduler.dialog.taskDesc") }}</span>
          </label>
          <textarea
            v-model="formData.description"
            class="textarea textarea-bordered"
            :placeholder="t('settings.scheduler.dialog.taskDescPlaceholder')"
            rows="2"
          />
        </div>

        <!-- Trigger Type -->
        <div class="form-control">
          <label class="label">
            <span class="label-text">{{ t("settings.scheduler.dialog.triggerType") }}</span>
          </label>
          <div class="flex flex-wrap gap-2">
            <label class="flex items-center gap-2 cursor-pointer">
              <input
                v-model="formData.trigger_type"
                type="radio"
                class="radio radio-primary"
                value="cron"
              />
              <span class="text-sm">{{ t("settings.scheduler.dialog.cronExpression") }}</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer">
              <input
                v-model="formData.trigger_type"
                type="radio"
                class="radio radio-primary"
                value="date"
              />
              <span class="text-sm">{{ t("settings.scheduler.dialog.specificTime") }}</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer">
              <input
                v-model="formData.trigger_type"
                type="radio"
                class="radio radio-primary"
                value="interval"
              />
              <span class="text-sm">{{ t("settings.scheduler.dialog.intervalExecution") }}</span>
            </label>
          </div>
        </div>

        <!-- Cron -->
        <template v-if="formData.trigger_type === 'cron'">
          <div class="form-control">
            <label class="label">
              <span class="label-text">{{ t("settings.scheduler.dialog.cronExpression") }}</span>
            </label>
            <input
              :value="cronConfig.cron"
              type="text"
              class="input input-bordered"
              :placeholder="t('settings.scheduler.dialog.cronPlaceholder')"
              @input="updateTriggerConfig({ cron: getInputValue($event) })"
            />
          </div>
          <div class="flex flex-wrap gap-2">
            <button class="btn btn-outline btn-xs" @click="setCronPreset('daily')">
              {{ t("settings.scheduler.dialog.presets.daily") }}
            </button>
            <button class="btn btn-outline btn-xs" @click="setCronPreset('daily9am')">
              {{ t("settings.scheduler.dialog.presets.daily9am") }}
            </button>
            <button class="btn btn-outline btn-xs" @click="setCronPreset('weekly')">
              {{ t("settings.scheduler.dialog.presets.weekly") }}
            </button>
            <button class="btn btn-outline btn-xs" @click="setCronPreset('hourly')">
              {{ t("settings.scheduler.dialog.presets.hourly") }}
            </button>
          </div>
        </template>

        <!-- Date -->
        <template v-if="formData.trigger_type === 'date'">
          <div class="form-control">
            <label class="label">
              <span class="label-text">{{ t("settings.scheduler.dialog.executionTime") }}</span>
            </label>
            <input
              type="datetime-local"
              class="input input-bordered"
              :value="dateConfigLocal"
              @input="
                updateTriggerConfig({
                  run_date: new Date(getInputValue($event)).toISOString(),
                })
              "
            />
          </div>
        </template>

        <!-- Interval -->
        <template v-if="formData.trigger_type === 'interval'">
          <div class="grid grid-cols-2 gap-3">
            <div class="form-control">
              <label class="label"
                ><span class="label-text">{{ t("settings.scheduler.formatter.week") }}</span></label
              >
              <input
                :value="intervalConfig.weeks"
                type="number"
                class="input input-bordered"
                min="0"
                @input="
                  updateTriggerConfig({
                    weeks: Number(getInputValue($event)) || 0,
                  })
                "
              />
            </div>
            <div class="form-control">
              <label class="label"
                ><span class="label-text">{{ t("settings.scheduler.formatter.day") }}</span></label
              >
              <input
                :value="intervalConfig.days"
                type="number"
                class="input input-bordered"
                min="0"
                @input="
                  updateTriggerConfig({
                    days: Number(getInputValue($event)) || 0,
                  })
                "
              />
            </div>
            <div class="form-control">
              <label class="label"
                ><span class="label-text">{{ t("settings.scheduler.formatter.hour") }}</span></label
              >
              <input
                :value="intervalConfig.hours"
                type="number"
                class="input input-bordered"
                min="0"
                @input="
                  updateTriggerConfig({
                    hours: Number(getInputValue($event)) || 0,
                  })
                "
              />
            </div>
            <div class="form-control">
              <label class="label"
                ><span class="label-text">{{
                  t("settings.scheduler.formatter.minute")
                }}</span></label
              >
              <input
                :value="intervalConfig.minutes"
                type="number"
                class="input input-bordered"
                min="0"
                @input="
                  updateTriggerConfig({
                    minutes: Number(getInputValue($event)) || 0,
                  })
                "
              />
            </div>
            <div class="form-control col-span-2">
              <label class="label"
                ><span class="label-text">{{
                  t("settings.scheduler.formatter.second")
                }}</span></label
              >
              <input
                :value="intervalConfig.seconds"
                type="number"
                class="input input-bordered"
                min="0"
                @input="
                  updateTriggerConfig({
                    seconds: Number(getInputValue($event)) || 0,
                  })
                "
              />
            </div>
          </div>
          <div class="form-control">
            <label class="label"
              ><span class="label-text">{{ t("settings.scheduler.dialog.startTime") }}</span></label
            >
            <input
              type="datetime-local"
              class="input input-bordered"
              :value="intervalStartLocal"
              @input="
                updateTriggerConfig({
                  start_date: getInputValue($event)
                    ? new Date(getInputValue($event)).toISOString()
                    : undefined,
                })
              "
            />
          </div>
          <div class="form-control">
            <label class="label"
              ><span class="label-text">{{ t("settings.scheduler.dialog.endTime") }}</span></label
            >
            <input
              type="datetime-local"
              class="input input-bordered"
              :value="intervalEndLocal"
              @input="
                updateTriggerConfig({
                  end_date: getInputValue($event)
                    ? new Date(getInputValue($event)).toISOString()
                    : undefined,
                })
              "
            />
          </div>
        </template>

        <div class="divider" />

        <!-- Device & Resource -->
        <div class="form-control">
          <label class="label">
            <span class="label-text">{{ t("settings.scheduler.dialog.controller") }}</span>
          </label>
          <select
            v-model="formData.controller_name"
            class="select select-bordered"
            :disabled="loadingDevices"
          >
            <option value="">{{ t("panel.selectDeviceType") }}</option>
            <option v-for="opt in deviceControllerOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>

        <div class="form-control">
          <label class="label">
            <span class="label-text">{{ t("settings.scheduler.dialog.deviceAddress") }}</span>
          </label>
          <input
            v-if="isPlayCover"
            v-model="selectedDeviceAddress"
            type="text"
            class="input input-bordered"
            :placeholder="t('panel.playcoverAddress')"
            :disabled="!formData.controller_name"
          />
          <select
            v-else
            v-model="selectedDeviceAddress"
            class="select select-bordered"
            :disabled="!formData.controller_name || loadingDevices"
          >
            <option value="">{{ t("panel.selectDevice") }}</option>
            <option v-for="opt in deviceAddressOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>

        <div class="form-control">
          <label class="label">
            <span class="label-text">{{ t("settings.scheduler.dialog.resource") }}</span>
          </label>
          <select
            v-model="formData.resource_name"
            class="select select-bordered"
            :disabled="!formData.controller_name || loadingResources"
          >
            <option value="">{{ t("panel.selectResource") }}</option>
            <option v-for="opt in resourceOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>

        <!-- Tabs -->
        <div class="tabs tabs-boxed mb-2">
          <a
            class="tab"
            :class="{ 'tab-active': activeTab === 'pre-tasks' }"
            @click="activeTab = 'pre-tasks'"
          >
            {{ t("settings.scheduler.dialog.tab.preTasks") }}
          </a>
          <a
            class="tab"
            :class="{ 'tab-active': activeTab === 'task-list' }"
            @click="activeTab = 'task-list'"
          >
            {{ t("settings.scheduler.dialog.tab.taskList") }}
          </a>
          <a
            class="tab"
            :class="{ 'tab-active': activeTab === 'task-settings' }"
            @click="activeTab = 'task-settings'"
          >
            {{ t("settings.scheduler.dialog.tab.taskSettings") }}
          </a>
        </div>

        <div class="max-h-64 overflow-y-auto">
          <div v-if="activeTab === 'pre-tasks'">
            <PreTaskList v-model="formData.preTasks" embedded />
          </div>
          <div v-if="activeTab === 'task-list'">
            <TaskSelectList
              :tasks="taskListData"
              :selected-tasks="formData.task_list"
              :controller-name="formData.controller_name"
              :resource-name="formData.resource_name"
              :hide-incompatible="true"
              @update:tasks="handleTasksUpdate"
              @update:selected-tasks="handleSelectedTasksUpdate"
              @config="openTaskSettings"
            />
          </div>
          <div v-if="activeTab === 'task-settings'">
            <TaskOptionPanel
              :current-task-id="currentSettingTaskId"
              :options="formData.task_options"
              :show-header="true"
              :header-label="t('settings.scheduler.dialog.currentSetting')"
              :empty-text="t('settings.scheduler.dialog.selectTaskTip')"
              :no-options-text="t('settings.scheduler.dialog.noOptions')"
            />
          </div>
        </div>
      </div>

      <div class="modal-action">
        <button class="btn btn-ghost" @click="handleCancel">{{ t("common.cancel") }}</button>
        <button class="btn btn-primary" :disabled="loading" @click="handleSave">
          <Icon v-if="loading" icon="mdi:loading" class="animate-spin mr-1 text-lg" />
          {{ t("common.save") }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import {
  useInterfaceStore,
  useSchedulerStore,
  useSettingsStore,
  useTaskConfigStore,
} from "@/stores"
import type { TaskListItem } from "@/types/taskConfigModel"
import TaskSelectList from "@/components/panel/task/TaskSelectList.vue"
import TaskOptionPanel from "@/components/panel/task/TaskOptionPanel.vue"
import PreTaskList from "@/components/panel/task/PreTaskList.vue"
import { resolveInterfaceText } from "@/utils/interface/content"
import { getDevices, getResource } from "@/services/api"
import type { ConnectableDevice, DeviceControllerType } from "@/services/api"
import { buildDeviceLabel } from "@/utils/panel/device"
import type { PanelLastConnectedDevice } from "@/types/settingsModel"
import type {
  ScheduledTask,
  ScheduledTaskCreate,
  TriggerType,
  TriggerConfig,
  CronTriggerConfig,
  DateTriggerConfig,
  IntervalTriggerConfig,
} from "@/types/schedulerModel"
import { showGlobalMessage } from "@/services/feedback/message"
import { tryCatch } from "@/utils/tryCatch"

interface Props {
  show: boolean
  task?: ScheduledTask | null
}

interface Emits {
  (e: "update:show", value: boolean): void
  (e: "saved"): void
}

const { show, task } = defineProps<Props>()
const emit = defineEmits<Emits>()

const { t, locale } = useI18n()
const schedulerStore = useSchedulerStore()
const configStore = useTaskConfigStore()
const interfaceStore = useInterfaceStore()
const settingsStore = useSettingsStore()

const loading = ref(false)

const activeTab = ref<"task-list" | "task-settings" | "pre-tasks">("task-list")
const currentSettingTaskId = ref<string | null>(null)
const suppressFormInit = ref(false)

const availableDevices = ref<ConnectableDevice[]>([])
const availableResources = ref<Array<{ name: string; label?: string; controller?: string[] }>>([])
const loadingDevices = ref(false)
const loadingResources = ref(false)

function isDeviceControllerType(type: string): type is DeviceControllerType {
  return type === "Adb" || type === "Win32" || type === "Gamepad" || type === "PlayCover"
}

function getInputValue(event: Event): string {
  const target = event.target
  return target instanceof HTMLInputElement ? target.value : ""
}

const showDialog = computed({
  get: () => show,
  set: (value) => emit("update:show", value),
})

const isEditMode = computed(() => !!task)
const availableTasks = computed(() => configStore.taskList)

const selectedControllerType = computed(() => {
  const controller = interfaceStore.interface?.controller?.find(
    (item) => item.name === formData.value.controller_name,
  )
  return controller?.type || null
})

const isPlayCover = computed(() => selectedControllerType.value === "PlayCover")

const deviceControllerOptions = computed(() =>
  (interfaceStore.interface?.controller || [])
    .filter((controller) => isDeviceControllerType(controller.type))
    .map((controller) => ({
      label: resolveInterfaceText(
        interfaceStore.interface,
        locale.value,
        controller.label,
        controller.name,
      ),
      value: controller.name,
    })),
)

const deviceAddressOptions = computed(() => {
  if (!formData.value.controller_name) {
    return []
  }

  const options = new Map<string, { label: string; value: string }>()
  for (const device of availableDevices.value) {
    const value = getDeviceAddressValue(device)
    options.set(value, { label: buildDeviceLabel(device), value })
  }

  const recentDevices = settingsStore.settings.panel.recentDevices ?? []
  for (const device of recentDevices) {
    if (device.controller_name !== formData.value.controller_name) {
      continue
    }
    const value = getStoredDeviceAddress(device)
    if (options.has(value)) {
      continue
    }
    options.set(value, { label: buildStoredDeviceLabel(device), value })
  }

  return Array.from(options.values())
})

const resourceOptions = computed(() =>
  availableResources.value.map((resource) => ({
    label: resolveInterfaceText(
      interfaceStore.interface,
      locale.value,
      resource.label,
      resource.name,
    ),
    value: resource.name,
  })),
)

const selectedDeviceAddress = computed<string | null>({
  get: () => formData.value.device?.device_address ?? null,
  set: (value) => {
    const controller = interfaceStore.interface?.controller?.find(
      (item) => item.name === formData.value.controller_name,
    )
    if (!controller || !value) {
      formData.value.device = null
      return
    }
    if (!isDeviceControllerType(controller.type)) {
      formData.value.device = null
      return
    }
    formData.value.device = {
      controller_name: controller.name,
      device_type: controller.type,
      device_address: value,
    }
  },
})

const cronConfig = computed<CronTriggerConfig>(() => {
  const config = formData.value.trigger_config
  return config.type === "cron" ? config : { type: "cron", cron: "" }
})
const dateConfig = computed<DateTriggerConfig>(() => {
  const config = formData.value.trigger_config
  return config.type === "date" ? config : { type: "date", run_date: "" }
})
const dateConfigLocal = computed(() => {
  if (!dateConfig.value.run_date) return ""
  const d = new Date(dateConfig.value.run_date)
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
})
const intervalConfig = computed<IntervalTriggerConfig>(() => {
  const config = formData.value.trigger_config
  return config.type === "interval" ? config : { type: "interval" }
})
const intervalStartLocal = computed(() => {
  if (!intervalConfig.value.start_date) return ""
  const d = new Date(intervalConfig.value.start_date)
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
})
const intervalEndLocal = computed(() => {
  if (!intervalConfig.value.end_date) return ""
  const d = new Date(intervalConfig.value.end_date)
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
})

const formData = ref<ScheduledTaskCreate>(initFormData(task))
const taskListData = ref<TaskListItem[]>([])

watch(
  () => formData.value.trigger_type,
  (newType) => {
    formData.value.trigger_config = getTriggerConfigByType(newType)
  },
)

watch(
  () => task,
  (newTask) => {
    suppressFormInit.value = true
    formData.value = initFormData(newTask)
    syncTaskListData(formData.value.task_list)
    void nextTick(() => {
      suppressFormInit.value = false
    })
  },
)

watch(
  () => formData.value.controller_name,
  (newVal, oldVal) => {
    const controller = interfaceStore.interface?.controller?.find((item) => item.name === newVal)
    const type = controller?.type

    if (!suppressFormInit.value && oldVal != null && oldVal !== newVal) {
      formData.value.device = null
      formData.value.resource_name = undefined
    }

    if (newVal && type) {
      void fetchDevices(newVal)
      void fetchResources(type)
      return
    }
    availableDevices.value = []
    availableResources.value = []
  },
)

watch(
  [() => formData.value.controller_name, () => formData.value.resource_name],
  ([controllerName, resourceName]) => {
    if (!showDialog.value || suppressFormInit.value) {
      return
    }

    const compatibleTaskIds = formData.value.task_list.filter((taskId) =>
      interfaceStore.isTaskCompatibleByEntry(taskId, controllerName, resourceName),
    )
    const removedCount = formData.value.task_list.length - compatibleTaskIds.length
    if (removedCount <= 0) {
      return
    }

    formData.value.task_list = compatibleTaskIds
    formData.value.task_options = configStore.buildOptionsForTasks(
      compatibleTaskIds,
      formData.value.task_options,
    )

    if (currentSettingTaskId.value && !compatibleTaskIds.includes(currentSettingTaskId.value)) {
      currentSettingTaskId.value = null
      activeTab.value = "task-list"
    }

    showGlobalMessage(
      "warning",
      t("settings.scheduler.dialog.removedIncompatibleTasks", {
        count: removedCount,
      }),
    )
  },
  { flush: "post" },
)

watch(
  availableTasks,
  () => {
    syncTaskListData(formData.value.task_list)
  },
  { immediate: true },
)

function resetForm() {
  formData.value = initFormData()
  syncTaskListData(formData.value.task_list)
  currentSettingTaskId.value = null
  activeTab.value = "task-list"
}

function syncTaskListData(preferredOrder: string[]) {
  const allTasks = availableTasks.value
  const taskMap = new Map(allTasks.map((task) => [task.id, task]))
  const orderedTasks: TaskListItem[] = []

  for (const taskId of preferredOrder) {
    const task = taskMap.get(taskId)
    if (task) {
      orderedTasks.push(task)
      taskMap.delete(taskId)
    }
  }

  for (const task of allTasks) {
    if (taskMap.has(task.id)) {
      orderedTasks.push(task)
    }
  }

  taskListData.value = orderedTasks
}

function buildOrderedTaskList(selectedTasks: string[], tasks: TaskListItem[] = taskListData.value) {
  const selectedSet = new Set(configStore.normalizeTaskIds(selectedTasks))
  return tasks.filter((task) => selectedSet.has(task.id)).map((task) => task.id)
}

function handleTasksUpdate(tasks: TaskListItem[]) {
  taskListData.value = tasks
  formData.value.task_list = buildOrderedTaskList(formData.value.task_list, tasks)
}

function initFormData(task?: ScheduledTask | null): ScheduledTaskCreate {
  if (task) {
    const task_list = configStore.normalizeTaskIds(task.task_list)
    return {
      name: task.name,
      description: task.description || "",
      enabled: task.enabled,
      trigger_type: task.trigger_type,
      trigger_config: getTriggerConfigByType(task.trigger_type, task.trigger_config),
      task_list,
      task_options: configStore.buildOptionsForTasks(task_list, task.task_options),
      preTasks: Array.isArray(task.preTasks) ? task.preTasks.map((pt) => ({ ...pt })) : [],
      controller_name: task.controller_name,
      device: task.device ? { ...task.device } : null,
      resource_name: task.resource_name,
    }
  }
  return {
    name: "",
    description: "",
    enabled: true,
    trigger_type: "cron",
    trigger_config: getTriggerConfigByType("cron"),
    task_list: [],
    task_options: configStore.buildOptionsForTasks([]),
    preTasks: [],
    controller_name: undefined,
    device: null,
    resource_name: undefined,
  }
}

function buildCronConfig(existing?: Partial<TriggerConfig>): CronTriggerConfig {
  const config = existing?.type === "cron" ? existing : undefined
  return { type: "cron", cron: config?.cron ?? "0 0 * * *" }
}

function buildDateConfig(existing?: Partial<TriggerConfig>): DateTriggerConfig {
  const config = existing?.type === "date" ? existing : undefined
  return { type: "date", run_date: config?.run_date ?? new Date().toISOString() }
}

function buildIntervalConfig(existing?: Partial<TriggerConfig>): IntervalTriggerConfig {
  const config = existing?.type === "interval" ? existing : undefined
  const result: IntervalTriggerConfig = {
    type: "interval",
    weeks: 0,
    days: 0,
    hours: 1,
    minutes: 0,
    seconds: 0,
  }
  if (config === undefined) {
    return result
  }
  if (config.weeks !== undefined) {
    result.weeks = config.weeks
  }
  if (config.days !== undefined) {
    result.days = config.days
  }
  if (config.hours !== undefined) {
    result.hours = config.hours
  }
  if (config.minutes !== undefined) {
    result.minutes = config.minutes
  }
  if (config.seconds !== undefined) {
    result.seconds = config.seconds
  }
  result.start_date = config.start_date
  result.end_date = config.end_date
  return result
}

function getTriggerConfigByType(
  type: TriggerType,
  existing?: Partial<TriggerConfig>,
): TriggerConfig {
  switch (type) {
    case "cron":
      return buildCronConfig(existing)
    case "date":
      return buildDateConfig(existing)
    case "interval":
      return buildIntervalConfig(existing)
    default:
      return buildCronConfig()
  }
}

function updateTriggerConfig(updates: Partial<TriggerConfig>) {
  formData.value.trigger_config = Object.assign({}, formData.value.trigger_config, updates)
}

function setCronPreset(preset: string) {
  const presets: Record<string, string> = {
    daily: "0 0 * * *",
    daily9am: "0 9 * * *",
    weekly: "0 0 * * 1",
    hourly: "0 * * * *",
  }
  updateTriggerConfig({ cron: presets[preset] })
}

function handleSelectedTasksUpdate(newSelectedTasks: string[]) {
  const task_list = buildOrderedTaskList(newSelectedTasks)
  formData.value.task_list = task_list
  formData.value.task_options = configStore.buildOptionsForTasks(
    task_list,
    formData.value.task_options,
  )
  if (currentSettingTaskId.value && !task_list.includes(currentSettingTaskId.value)) {
    currentSettingTaskId.value = null
    activeTab.value = "task-list"
  }
}

function openTaskSettings(taskId: string) {
  if (!formData.value.task_list.includes(taskId)) {
    const task_list = buildOrderedTaskList([...formData.value.task_list, taskId])
    formData.value.task_list = task_list
    formData.value.task_options = configStore.buildOptionsForTasks(
      task_list,
      formData.value.task_options,
    )
  }
  currentSettingTaskId.value = taskId
  activeTab.value = "task-settings"
}

function getDeviceAddressValue(device: ConnectableDevice): string {
  if (device.type === "Adb") {
    return device.address
  }
  if (device.type === "Win32") {
    return String(device.hWnd)
  }
  if (device.type === "Gamepad") {
    return `${device.hWnd}|${device.gamepad_type}`
  }
  return device.address
}

function getStoredDeviceAddress(device: PanelLastConnectedDevice): string {
  if (device.type === "Adb") {
    return device.address
  }
  if (device.type === "Win32") {
    return String(device.hWnd)
  }
  if (device.type === "Gamepad") {
    return `${device.hWnd}|${device.gamepad_type}`
  }
  return device.address
}

function buildStoredDeviceLabel(device: PanelLastConnectedDevice): string {
  if (device.type === "Adb") {
    return device.address
  }
  if (device.type === "Win32" || device.type === "Gamepad") {
    const name = device.window_name || device.class_name
    return name ? `${name} (${device.hWnd})` : String(device.hWnd)
  }
  return device.address
}

async function fetchDevices(controllerName: string) {
  loadingDevices.value = true
  const [data, err] = await tryCatch(() => getDevices(controllerName))
  loadingDevices.value = false
  if (err) {
    console.error("Failed to fetch devices:", err)
    availableDevices.value = []
    return
  }
  availableDevices.value = data.devices
}

async function fetchResources(controllerType: string) {
  loadingResources.value = true
  const [data, err] = await tryCatch(() => getResource(controllerType))
  loadingResources.value = false
  if (err) {
    console.error("Failed to fetch resources:", err)
    availableResources.value = []
    return
  }
  availableResources.value = data
}

function validateName(): boolean {
  const name = formData.value.name.trim()
  if (!name) {
    showGlobalMessage("error", t("settings.scheduler.rules.nameRequired"))
    return false
  }
  if (name.length > 100) {
    showGlobalMessage("error", t("settings.scheduler.rules.nameLength"))
    return false
  }
  return true
}

function validateCron(): boolean {
  const config = formData.value.trigger_config
  if (config.type !== "cron") {
    return false
  }
  if (!config.cron) {
    showGlobalMessage("error", t("settings.scheduler.rules.cronRequired"))
    return false
  }
  const pattern =
    /^(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)$/
  if (!pattern.test(config.cron)) {
    showGlobalMessage("error", t("settings.scheduler.rules.cronInvalid"))
    return false
  }
  return true
}

function validateDate(): boolean {
  const config = formData.value.trigger_config
  if (config.type !== "date") {
    return false
  }
  if (!config.run_date) {
    showGlobalMessage("error", t("settings.scheduler.rules.dateRequired"))
    return false
  }
  if (new Date(config.run_date).getTime() < Date.now()) {
    showGlobalMessage("error", t("settings.scheduler.rules.dateInPast"))
    return false
  }
  return true
}

function nonNegative(value: number | undefined): number {
  return value || 0
}

function validateInterval(): boolean {
  const config = formData.value.trigger_config
  if (config.type !== "interval") {
    return false
  }
  const total =
    nonNegative(config.weeks) +
    nonNegative(config.days) +
    nonNegative(config.hours) +
    nonNegative(config.minutes) +
    nonNegative(config.seconds)
  if (total <= 0) {
    showGlobalMessage("error", t("settings.scheduler.rules.intervalRequired"))
    return false
  }
  if (config.start_date && config.end_date) {
    const startAt = new Date(config.start_date).getTime()
    const endAt = new Date(config.end_date).getTime()
    if (endAt < startAt) {
      showGlobalMessage("error", t("settings.scheduler.rules.endBeforeStart"))
      return false
    }
  }
  return true
}

function validateTaskList(): boolean {
  if (formData.value.task_list.length === 0) {
    showGlobalMessage("error", t("settings.scheduler.rules.taskListRequired"))
    return false
  }
  return true
}

function validateForm(): boolean {
  if (!validateName()) {
    return false
  }
  const { trigger_type } = formData.value
  if (trigger_type === "cron" && !validateCron()) {
    return false
  }
  if (trigger_type === "date" && !validateDate()) {
    return false
  }
  if (trigger_type === "interval" && !validateInterval()) {
    return false
  }
  return validateTaskList()
}

async function handleSave() {
  if (!validateForm()) {
    return
  }

  loading.value = true
  const taskPayload = {
    ...formData.value,
    ...configStore.buildExecutionPayload(formData.value.task_list, formData.value.task_options),
    preTasks: formData.value.preTasks ?? [],
  }
  const [success, err] = await tryCatch(() =>
    isEditMode.value && task
      ? schedulerStore.updateTask(task.id, taskPayload)
      : schedulerStore.createTask(taskPayload),
  )
  loading.value = false
  if (err || !success) {
    showGlobalMessage("error", schedulerStore.error || t("settings.scheduler.dialog.saveFail"))
    return
  }

  showGlobalMessage(
    "success",
    isEditMode.value
      ? t("settings.scheduler.dialog.taskUpdated")
      : t("settings.scheduler.dialog.taskCreated"),
  )
  showDialog.value = false
  emit("saved")
  resetForm()
}

function handleCancel() {
  showDialog.value = false
  resetForm()
}
</script>
