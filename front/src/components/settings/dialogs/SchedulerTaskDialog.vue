<template>
  <n-modal
    v-model:show="showDialog"
    preset="card"
    :title="
      isEditMode
        ? t('settings.scheduler.dialog.editTitle')
        : t('settings.scheduler.dialog.createTitle')
    "
    class="xl:w-45% w-95"
  >
    <n-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-placement="left"
      label-width="100"
    >
      <n-form-item :label="t('settings.scheduler.dialog.taskName')" path="name">
        <n-input
          v-model:value="formData.name"
          :placeholder="t('settings.scheduler.dialog.taskNamePlaceholder')"
        />
      </n-form-item>

      <n-form-item :label="t('settings.scheduler.dialog.taskDesc')" path="description">
        <n-input
          v-model:value="formData.description"
          type="textarea"
          :placeholder="t('settings.scheduler.dialog.taskDescPlaceholder')"
          :autosize="{ minRows: 2, maxRows: 4 }"
        />
      </n-form-item>

      <n-form-item :label="t('settings.scheduler.dialog.triggerType')" path="trigger_type">
        <n-radio-group v-model:value="formData.trigger_type">
          <n-radio value="cron">{{ t("settings.scheduler.dialog.cronExpression") }}</n-radio>
          <n-radio value="date">{{ t("settings.scheduler.dialog.specificTime") }}</n-radio>
          <n-radio value="interval">{{ t("settings.scheduler.dialog.intervalExecution") }}</n-radio>
        </n-radio-group>
      </n-form-item>

      <!-- Cron 表达式编辑器 -->
      <template v-if="formData.trigger_type === 'cron'">
        <n-form-item
          :label="t('settings.scheduler.dialog.cronExpression')"
          path="trigger_config.cron"
        >
          <n-input
            :value="cronConfig.cron"
            @update:value="(v: string) => updateTriggerConfig({ cron: v })"
            :placeholder="t('settings.scheduler.dialog.cronPlaceholder')"
          />
        </n-form-item>
        <n-form-item :label="t('settings.scheduler.dialog.quickSelect')">
          <n-space>
            <n-button size="small" @click="setCronPreset('daily')">{{
              t("settings.scheduler.dialog.presets.daily")
            }}</n-button>
            <n-button size="small" @click="setCronPreset('daily9am')">{{
              t("settings.scheduler.dialog.presets.daily9am")
            }}</n-button>
            <n-button size="small" @click="setCronPreset('weekly')">{{
              t("settings.scheduler.dialog.presets.weekly")
            }}</n-button>
            <n-button size="small" @click="setCronPreset('hourly')">{{
              t("settings.scheduler.dialog.presets.hourly")
            }}</n-button>
          </n-space>
        </n-form-item>
      </template>

      <!-- Date 触发器 -->
      <template v-if="formData.trigger_type === 'date'">
        <n-form-item
          :label="t('settings.scheduler.dialog.executionTime')"
          path="trigger_config.run_date"
        >
          <n-date-picker
            :value="dateConfigTimestamp"
            @update:value="
              (v: number | null) =>
                updateTriggerConfig({
                  run_date: v ? new Date(v).toISOString() : new Date().toISOString(),
                })
            "
            type="datetime"
            :placeholder="t('settings.scheduler.dialog.selectTime')"
            style="width: 100%"
          />
        </n-form-item>
      </template>

      <!-- Interval 触发器 -->
      <template v-if="formData.trigger_type === 'interval'">
        <n-form-item :label="t('settings.scheduler.dialog.intervalTime')" path="trigger_config">
          <n-grid :cols="2" :x-gap="12" :y-gap="12" style="width: 100%">
            <n-gi>
              <n-input-number
                :value="intervalConfig.weeks"
                @update:value="(v: number | null) => updateTriggerConfig({ weeks: v ?? 0 })"
                :min="0"
                style="width: 100%"
              >
                <template #suffix>{{ t("settings.scheduler.formatter.week") }}</template>
              </n-input-number>
            </n-gi>
            <n-gi>
              <n-input-number
                :value="intervalConfig.days"
                @update:value="(v: number | null) => updateTriggerConfig({ days: v ?? 0 })"
                :min="0"
                style="width: 100%"
              >
                <template #suffix>{{ t("settings.scheduler.formatter.day") }}</template>
              </n-input-number>
            </n-gi>
            <n-gi>
              <n-input-number
                :value="intervalConfig.hours"
                @update:value="(v: number | null) => updateTriggerConfig({ hours: v ?? 0 })"
                :min="0"
                style="width: 100%"
              >
                <template #suffix>{{ t("settings.scheduler.formatter.hour") }}</template>
              </n-input-number>
            </n-gi>
            <n-gi>
              <n-input-number
                :value="intervalConfig.minutes"
                @update:value="(v: number | null) => updateTriggerConfig({ minutes: v ?? 0 })"
                :min="0"
                style="width: 100%"
              >
                <template #suffix>{{ t("settings.scheduler.formatter.minute") }}</template>
              </n-input-number>
            </n-gi>
            <n-gi :span="2">
              <n-input-number
                :value="intervalConfig.seconds"
                @update:value="(v: number | null) => updateTriggerConfig({ seconds: v ?? 0 })"
                :min="0"
                style="width: 100%"
              >
                <template #suffix>{{ t("settings.scheduler.formatter.second") }}</template>
              </n-input-number>
            </n-gi>
          </n-grid>
        </n-form-item>
        <n-form-item :label="t('settings.scheduler.dialog.startTime')" path="trigger_config">
          <n-date-picker
            :value="intervalStartTimestamp"
            @update:value="
              (v: number | null) =>
                updateTriggerConfig({
                  start_date: v ? new Date(v).toISOString() : undefined,
                })
            "
            type="datetime"
            clearable
            :placeholder="t('settings.scheduler.dialog.selectStartTime')"
            style="width: 100%"
          />
        </n-form-item>
        <n-form-item :label="t('settings.scheduler.dialog.endTime')" path="trigger_config">
          <n-date-picker
            :value="intervalEndTimestamp"
            @update:value="
              (v: number | null) =>
                updateTriggerConfig({
                  end_date: v ? new Date(v).toISOString() : undefined,
                })
            "
            type="datetime"
            clearable
            :placeholder="t('settings.scheduler.dialog.selectEndTime')"
            style="width: 100%"
          />
        </n-form-item>
      </template>

      <n-divider title-placement="left">
        {{ t("settings.scheduler.dialog.deviceAndResource") }}
      </n-divider>

      <n-form-item :label="t('settings.scheduler.dialog.controller')" path="controller_name">
        <n-select
          v-model:value="formData.controller_name"
          :placeholder="t('panel.selectDeviceType')"
          :options="deviceControllerOptions"
          :loading="loadingDevices"
          clearable
        />
      </n-form-item>

      <n-form-item :label="t('settings.scheduler.dialog.deviceAddress')" path="device">
        <n-input
          v-if="isPlayCover"
          v-model:value="selectedDeviceAddress"
          :placeholder="t('panel.playcoverAddress')"
          :disabled="!formData.controller_name"
        />
        <n-select
          v-else
          v-model:value="selectedDeviceAddress"
          :placeholder="t('panel.selectDevice')"
          :options="deviceAddressOptions"
          :loading="loadingDevices"
          :disabled="!formData.controller_name"
          filterable
          tag
          clearable
        />
      </n-form-item>

      <n-form-item :label="t('settings.scheduler.dialog.resource')" path="resource_name">
        <n-select
          v-model:value="formData.resource_name"
          :placeholder="t('panel.selectResource')"
          :options="resourceOptions"
          :loading="loadingResources"
          :disabled="!formData.controller_name"
          clearable
        />
      </n-form-item>

      <n-tabs v-model:value="activeTab" type="segment" animated>
        <!-- Tab 1: 前置任务 -->
        <n-tab-pane name="pre-tasks" :tab="t('settings.scheduler.dialog.tab.preTasks')">
          <n-scrollbar trigger="none" class="max-h-65 !rounded-[12px]">
            <PreTaskList v-model="formData.preTasks" embedded />
          </n-scrollbar>
        </n-tab-pane>

        <!-- Tab 2: 任务列表 -->
        <n-tab-pane name="task-list" :tab="t('settings.scheduler.dialog.tab.taskList')">
          <n-scrollbar trigger="none" class="max-h-65 !rounded-[12px]">
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
          </n-scrollbar>
        </n-tab-pane>

        <!-- Tab 3: 任务设置 -->
        <n-tab-pane name="task-settings" :tab="t('settings.scheduler.dialog.tab.taskSettings')">
          <TaskOptionPanel
            :current-task-id="currentSettingTaskId"
            :options="formData.task_options"
            :show-header="true"
            :header-label="t('settings.scheduler.dialog.currentSetting')"
            :empty-text="t('settings.scheduler.dialog.selectTaskTip')"
            :no-options-text="t('settings.scheduler.dialog.noOptions')"
          />
        </n-tab-pane>
      </n-tabs>
    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="handleCancel">{{ t("common.cancel") }}</n-button>
        <n-button type="primary" @click="handleSave" :loading="loading">{{
          t("common.save")
        }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch } from "vue"
import { useMessage, type FormInst, type FormRules } from "naive-ui"
import { useI18n } from "vue-i18n"
import {
  useInterfaceStore,
  useSchedulerStore,
  useSettingsStore,
  useTaskConfigStore,
} from "@/stores"
import type { TaskListItem } from "@/types/task-config/model"
import TaskSelectList from "@/components/panel/task/TaskSelectList.vue"
import TaskOptionPanel from "@/components/panel/task/TaskOptionPanel.vue"
import PreTaskList from "@/components/panel/task/PreTaskList.vue"
import { resolveInterfaceText } from "@/utils/interface/content"
import { getDevices, getResource } from "@/services/api"
import type { ConnectableDevice, DeviceControllerType } from "@/services/api"
import { buildDeviceLabel } from "@/utils/panel/device"
import type { PanelLastConnectedDevice } from "@/types/settings/model"
import type {
  ScheduledTask,
  ScheduledTaskCreate,
  TriggerType,
  TriggerConfig,
  CronTriggerConfig,
  DateTriggerConfig,
  IntervalTriggerConfig,
} from "@/types/scheduler/model"

interface Props {
  show: boolean
  task?: ScheduledTask | null
}

interface Emits {
  (e: "update:show", value: boolean): void
  (e: "saved"): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const message = useMessage()
const { t, locale } = useI18n()
const schedulerStore = useSchedulerStore()
const configStore = useTaskConfigStore()
const interfaceStore = useInterfaceStore()
const settingsStore = useSettingsStore()

const formRef = ref<FormInst | null>(null)
const loading = ref(false)

const activeTab = ref<"task-list" | "task-settings" | "pre-tasks">("task-list")
const currentSettingTaskId = ref<string | null>(null)
const suppressFormInit = ref(false)

const availableDevices = ref<ConnectableDevice[]>([])
const availableResources = ref<Array<{ name: string; label?: string; controller?: string[] }>>([])
const loadingDevices = ref(false)
const loadingResources = ref(false)

const SUPPORTED_DEVICE_TYPES = new Set<DeviceControllerType>([
  "Adb",
  "Win32",
  "Gamepad",
  "PlayCover",
])

const showDialog = computed({
  get: () => props.show,
  set: (value) => emit("update:show", value),
})

const isEditMode = computed(() => !!props.task)
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
    .filter((controller) => SUPPORTED_DEVICE_TYPES.has(controller.type as DeviceControllerType))
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
    formData.value.device = {
      controller_name: controller.name,
      device_type: controller.type as DeviceControllerType,
      device_address: value,
    }
  },
})

// 触发器配置的 computed 属性
const cronConfig = computed(() => formData.value.trigger_config as CronTriggerConfig)
const dateConfig = computed(() => formData.value.trigger_config as DateTriggerConfig)
const dateConfigTimestamp = computed(() =>
  dateConfig.value.run_date ? new Date(dateConfig.value.run_date).getTime() : null,
)
const intervalConfig = computed(() => formData.value.trigger_config as IntervalTriggerConfig)
const intervalStartTimestamp = computed(() =>
  intervalConfig.value.start_date ? new Date(intervalConfig.value.start_date).getTime() : null,
)
const intervalEndTimestamp = computed(() =>
  intervalConfig.value.end_date ? new Date(intervalConfig.value.end_date).getTime() : null,
)

const formData = ref<ScheduledTaskCreate>(initFormData(props.task))
const taskListData = ref<TaskListItem[]>([])

const formRules = computed<FormRules>(() => ({
  name: [
    { required: true, message: t("settings.scheduler.rules.nameRequired"), trigger: "blur" },
    { min: 1, max: 100, message: t("settings.scheduler.rules.nameLength"), trigger: "blur" },
  ],
  "trigger_config.cron": [
    {
      validator: (rule, value: string) => {
        if (formData.value.trigger_type !== "cron") return true
        if (!value) return new Error(t("settings.scheduler.rules.cronRequired"))
        const pattern =
          /^(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)$/
        if (!pattern.test(value)) return new Error(t("settings.scheduler.rules.cronInvalid"))
        return true
      },
      trigger: ["blur", "input"],
    },
  ],
  "trigger_config.run_date": [
    {
      validator: (rule, value: string) => {
        if (formData.value.trigger_type !== "date") return true
        if (!value) return new Error(t("settings.scheduler.rules.dateRequired"))
        if (new Date(value).getTime() < Date.now())
          return new Error(t("settings.scheduler.rules.dateInPast"))
        return true
      },
      trigger: ["blur", "change"],
    },
  ],
  trigger_config: [
    {
      validator: (rule, value: IntervalTriggerConfig) => {
        if (formData.value.trigger_type !== "interval") return true
        const total =
          (value.weeks || 0) +
          (value.days || 0) +
          (value.hours || 0) +
          (value.minutes || 0) +
          (value.seconds || 0)
        if (total <= 0) {
          return new Error(t("settings.scheduler.rules.intervalRequired"))
        }
        if (value.start_date && value.end_date) {
          const startAt = new Date(value.start_date).getTime()
          const endAt = new Date(value.end_date).getTime()
          if (endAt < startAt) return new Error(t("settings.scheduler.rules.endBeforeStart"))
        }
        return true
      },
      trigger: ["blur", "change"],
    },
  ],
  task_list: [
    {
      type: "array",
      required: true,
      min: 1,
      message: t("settings.scheduler.rules.taskListRequired"),
      trigger: "change",
    },
  ],
}))

// 监听触发器类型变化，更新 trigger_config
watch(
  () => formData.value.trigger_type,
  (newType) => {
    formData.value.trigger_config = getTriggerConfigByType(newType)
  },
)

// 监听编辑模式，填充表单
watch(
  () => props.task,
  (task) => {
    suppressFormInit.value = true
    formData.value = initFormData(task)
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
    } else {
      availableDevices.value = []
      availableResources.value = []
    }
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

    message.warning(
      t("settings.scheduler.dialog.removedIncompatibleTasks", {
        count: removedCount,
      }),
    )
  },
  { flush: "post" },
)

// 监听可用任务变化，更新可拖拽任务列表
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

// 初始化表单数据
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

// 根据类型获取触发器配置
function getTriggerConfigByType(
  type: TriggerType,
  existing?: Partial<TriggerConfig>,
): TriggerConfig {
  switch (type) {
    case "cron":
      return { type: "cron", cron: (existing as CronTriggerConfig)?.cron ?? "0 0 * * *" }
    case "date":
      return {
        type: "date",
        run_date: (existing as DateTriggerConfig)?.run_date ?? new Date().toISOString(),
      }
    case "interval":
      const interval = existing as IntervalTriggerConfig | undefined
      return {
        type: "interval",
        weeks: interval?.weeks ?? 0,
        days: interval?.days ?? 0,
        hours: interval?.hours ?? 1,
        minutes: interval?.minutes ?? 0,
        seconds: interval?.seconds ?? 0,
        start_date: interval?.start_date,
        end_date: interval?.end_date,
      } as IntervalTriggerConfig
    default:
      return { type: "cron", cron: "0 0 * * *" }
  }
}

function updateTriggerConfig(updates: Partial<TriggerConfig>) {
  formData.value.trigger_config = {
    ...formData.value.trigger_config,
    ...updates,
  } as TriggerConfig
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

// 处理任务选择更新
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
  try {
    const data = await getDevices(controllerName)
    availableDevices.value = data.devices
  } catch (error) {
    console.error("Failed to fetch devices:", error)
    availableDevices.value = []
  } finally {
    loadingDevices.value = false
  }
}

async function fetchResources(controllerType: string) {
  loadingResources.value = true
  try {
    availableResources.value = await getResource(controllerType)
  } catch (error) {
    console.error("Failed to fetch resources:", error)
    availableResources.value = []
  } finally {
    loadingResources.value = false
  }
}

async function handleSave() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  loading.value = true
  try {
    const taskPayload = {
      ...formData.value,
      ...configStore.buildExecutionPayload(formData.value.task_list, formData.value.task_options),
      preTasks: formData.value.preTasks ?? [],
    }
    let success
    if (isEditMode.value && props.task) {
      success = await schedulerStore.updateTask(props.task.id, taskPayload)
    } else {
      success = await schedulerStore.createTask(taskPayload)
    }

    if (success) {
      message.success(
        isEditMode.value
          ? t("settings.scheduler.dialog.taskUpdated")
          : t("settings.scheduler.dialog.taskCreated"),
      )
      showDialog.value = false
      emit("saved")
      resetForm()
    } else {
      message.error(schedulerStore.error || t("settings.scheduler.dialog.saveFail"))
    }
  } catch (e) {
    message.error(t("settings.scheduler.dialog.saveFail"))
    console.error("Failed to save task:", e)
  } finally {
    loading.value = false
  }
}

function handleCancel() {
  showDialog.value = false
  resetForm()
}
</script>
