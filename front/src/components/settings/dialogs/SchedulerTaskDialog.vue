<template>
  <NModal
    v-model:show="showDialog"
    preset="card"
    :closable="false"
    :mask-closable="true"
    :style="dialogBoxStyle"
    content-style="padding: 0"
  >
    <div
      class="flex h-[min(92dvh,540px)] w-full max-w-4xl flex-col sm:h-[min(90dvh,540px)] sm:max-h-none"
    >
      <!-- Header -->
      <header
        class="border-[var(--divider-color)] flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3 sm:px-5"
      >
        <div class="flex min-w-0 items-center gap-2">
          <NIcon size="20" class="shrink-0 text-[var(--primary-color)]">
            <CalendarOutline />
          </NIcon>
          <h3 class="truncate text-base font-semibold sm:text-lg">
            {{
              isEditMode
                ? t("settings.scheduler.dialog.editTitle")
                : t("settings.scheduler.dialog.createTitle")
            }}
          </h3>
        </div>
        <NButton
          quaternary
          circle
          size="small"
          class="shrink-0"
          :title="t('common.cancel')"
          :aria-label="t('common.cancel')"
          @click="handleCancel"
        >
          <template #icon>
            <NIcon size="18"><CloseOutline /></NIcon>
          </template>
        </NButton>
      </header>

      <!-- Body: section nav + scrollable content -->
      <div class="flex min-h-0 flex-1 flex-col md:flex-row">
        <!-- Section navigation -->
        <SchedulerTaskDialogSectionNav
          v-model:active-section="activeSection"
          :sections="sections"
        />

        <!-- Scrollable content -->
        <div
          class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5"
        >
          <!-- Basic info -->
          <div v-if="activeSection === 'basic'" class="space-y-1.5">
            <label class="flex items-center gap-1.5 text-sm font-medium">
              <NIcon size="16" class="opacity-70"><TextOutline /></NIcon>
              {{ t("settings.scheduler.dialog.taskName") }}
            </label>
            <NInput
              v-model:value="formData.name"
              size="medium"
              class="w-full"
              :placeholder="t('settings.scheduler.dialog.taskNamePlaceholder')"
              :input-props="{ autocomplete: 'off' }"
            />
          </div>

          <div v-if="activeSection === 'basic'" class="space-y-1.5">
            <label class="flex items-center gap-1.5 text-sm font-medium">
              <NIcon size="16" class="opacity-70"><TextOutline /></NIcon>
              {{ t("settings.scheduler.dialog.taskDesc") }}
            </label>
            <NInput
              v-model:value="formData.description"
              type="textarea"
              size="medium"
              class="w-full"
              :placeholder="t('settings.scheduler.dialog.taskDescPlaceholder')"
              :autosize="{ minRows: 3, maxRows: 5 }"
            />
          </div>

          <!-- Schedule: trigger type -->
          <SchedulerTaskDialogTriggerType
            v-if="activeSection === 'schedule'"
            :trigger-type="triggerType"
            :trigger-options="triggerOptions"
            @update:trigger-type="handleTriggerTypeChange"
          />

          <!-- Schedule: cron -->
          <div v-if="activeSection === 'schedule' && triggerType === 'cron'" class="space-y-1.5">
            <label class="text-sm font-medium">
              {{ t("settings.scheduler.dialog.cronExpression") }}
            </label>
            <NInput
              :value="cronConfig.cron"
              size="medium"
              class="w-full font-mono text-sm"
              :placeholder="t('settings.scheduler.dialog.cronPlaceholder')"
              :input-props="{ spellcheck: false }"
              @update:value="updateTriggerConfig({ cron: $event })"
            />
          </div>
          <div
            v-if="activeSection === 'schedule' && triggerType === 'cron'"
            class="flex flex-wrap gap-2"
          >
            <span class="self-center text-xs text-[var(--text-color-3)]">
              {{ t("settings.scheduler.dialog.quickSelect") }}
            </span>
            <NButton size="tiny" secondary @click="setCronPreset('daily')">
              {{ t("settings.scheduler.dialog.presets.daily") }}
            </NButton>
            <NButton size="tiny" secondary @click="setCronPreset('daily9am')">
              {{ t("settings.scheduler.dialog.presets.daily9am") }}
            </NButton>
            <NButton size="tiny" secondary @click="setCronPreset('weekly')">
              {{ t("settings.scheduler.dialog.presets.weekly") }}
            </NButton>
            <NButton size="tiny" secondary @click="setCronPreset('hourly')">
              {{ t("settings.scheduler.dialog.presets.hourly") }}
            </NButton>
          </div>

          <!-- Schedule: wakeup -->
          <div v-if="activeSection === 'schedule' && triggerType === 'cron'" class="space-y-1.5">
            <label class="flex items-center gap-1.5 text-sm font-medium">
              <NIcon size="16" class="opacity-70"><MoonOutline /></NIcon>
              {{ t("settings.scheduler.dialog.runWhenClosed") }}
            </label>
            <div class="flex flex-wrap items-center gap-3">
              <NSwitch
                v-model:value="wakeupEnabled"
                size="small"
                :disabled="!isCronNativeEligible"
              />
              <span v-if="!isCronNativeEligible" class="text-xs text-[var(--warning-color)]">
                {{ t("settings.scheduler.dialog.runWhenClosedIneligible") }}
              </span>
            </div>
          </div>

          <!-- Schedule: date -->
          <div v-if="activeSection === 'schedule' && triggerType === 'date'" class="space-y-1.5">
            <label class="text-sm font-medium">
              {{ t("settings.scheduler.dialog.executionTime") }}
            </label>
            <NInput
              :value="dateConfigLocal"
              size="medium"
              class="w-full max-w-xs"
              :input-props="{ type: 'datetime-local' }"
              @update:value="updateTriggerConfig({ run_date: toIsoOrEmpty($event) })"
            />
          </div>

          <!-- Schedule: interval duration -->
          <div
            v-if="activeSection === 'schedule' && triggerType === 'interval'"
            class="space-y-1.5"
          >
            <label class="text-sm font-medium">
              {{ t("settings.scheduler.dialog.intervalTime") }}
            </label>
            <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <label class="flex flex-col gap-1">
                <span class="text-xs opacity-60">{{ t("settings.scheduler.formatter.week") }}</span>
                <NInputNumber
                  :value="intervalConfig.weeks ?? 0"
                  :min="0"
                  size="medium"
                  class="w-full"
                  @update:value="updateTriggerConfig({ weeks: $event ?? 0 })"
                />
              </label>
              <label class="flex flex-col gap-1">
                <span class="text-xs opacity-60">{{ t("settings.scheduler.formatter.day") }}</span>
                <NInputNumber
                  :value="intervalConfig.days ?? 0"
                  :min="0"
                  size="medium"
                  class="w-full"
                  @update:value="updateTriggerConfig({ days: $event ?? 0 })"
                />
              </label>
              <label class="flex flex-col gap-1">
                <span class="text-xs opacity-60">{{ t("settings.scheduler.formatter.hour") }}</span>
                <NInputNumber
                  :value="intervalConfig.hours ?? 0"
                  :min="0"
                  size="medium"
                  class="w-full"
                  @update:value="updateTriggerConfig({ hours: $event ?? 0 })"
                />
              </label>
              <label class="flex flex-col gap-1">
                <span class="text-xs opacity-60">{{
                  t("settings.scheduler.formatter.minute")
                }}</span>
                <NInputNumber
                  :value="intervalConfig.minutes ?? 0"
                  :min="0"
                  size="medium"
                  class="w-full"
                  @update:value="updateTriggerConfig({ minutes: $event ?? 0 })"
                />
              </label>
              <label class="col-span-2 flex flex-col gap-1 sm:col-span-1">
                <span class="text-xs opacity-60">{{
                  t("settings.scheduler.formatter.second")
                }}</span>
                <NInputNumber
                  :value="intervalConfig.seconds ?? 0"
                  :min="0"
                  size="medium"
                  class="w-full"
                  @update:value="updateTriggerConfig({ seconds: $event ?? 0 })"
                />
              </label>
            </div>
          </div>

          <!-- Schedule: interval start/end -->
          <div
            v-if="activeSection === 'schedule' && triggerType === 'interval'"
            class="grid grid-cols-1 gap-3 sm:grid-cols-2"
          >
            <div class="space-y-1.5">
              <label class="text-sm font-medium">
                {{ t("settings.scheduler.dialog.startTime") }}
              </label>
              <NInput
                :value="intervalStartLocal"
                size="medium"
                class="w-full"
                :input-props="{ type: 'datetime-local' }"
                @update:value="
                  updateTriggerConfig({
                    start_date: toIsoOrEmpty($event) || undefined,
                  })
                "
              />
            </div>
            <div class="space-y-1.5">
              <label class="text-sm font-medium">
                {{ t("settings.scheduler.dialog.endTime") }}
              </label>
              <NInput
                :value="intervalEndLocal"
                size="medium"
                class="w-full"
                :input-props="{ type: 'datetime-local' }"
                @update:value="
                  updateTriggerConfig({
                    end_date: toIsoOrEmpty($event) || undefined,
                  })
                "
              />
            </div>
          </div>

          <!-- Environment -->
          <div v-if="activeSection === 'environment'" class="space-y-1.5">
            <label class="flex items-center gap-1.5 text-sm font-medium">
              <NIcon size="16" class="opacity-70"><GameControllerOutline /></NIcon>
              {{ t("settings.scheduler.dialog.controller") }}
            </label>
            <NSelect
              v-model:value="formData.controller_name"
              :options="deviceControllerOptions"
              :placeholder="t('panel.selectDeviceType')"
              :disabled="loadingDevices"
              size="medium"
              class="w-full"
            />
          </div>

          <div v-if="activeSection === 'environment'" class="space-y-1.5">
            <label class="flex items-center gap-1.5 text-sm font-medium">
              <NIcon size="16" class="opacity-70"><PhonePortraitOutline /></NIcon>
              {{ t("settings.scheduler.dialog.deviceAddress") }}
            </label>
            <NInput
              v-if="isPlayCover"
              v-model:value="selectedDeviceAddress"
              size="medium"
              class="w-full"
              :placeholder="t('panel.playcoverAddress')"
              :disabled="!formData.controller_name"
            />
            <NSelect
              v-else
              filterable
              tag
              :value="selectedDeviceAddress"
              :options="deviceAddressOptions"
              :placeholder="t('panel.selectDevice')"
              :disabled="!formData.controller_name || loadingDevices"
              size="medium"
              class="w-full"
              :on-create="(label: string) => ({ label, value: label })"
              @update:value="handleDeviceAddressUpdate"
            />
          </div>

          <div v-if="activeSection === 'environment'" class="space-y-1.5">
            <label class="flex items-center gap-1.5 text-sm font-medium">
              <NIcon size="16" class="opacity-70"><FolderOpenOutline /></NIcon>
              {{ t("settings.scheduler.dialog.resource") }}
            </label>
            <NSelect
              v-model:value="formData.resource_name"
              :options="resourceOptions"
              :placeholder="t('panel.selectResource')"
              :disabled="!formData.controller_name || loadingResources"
              size="medium"
              class="w-full"
            />
          </div>

          <!-- Content: tasks -->
          <SchedulerTaskDialogContentTabs
            v-if="activeSection === 'content'"
            v-model:active-tab="activeTab"
            v-model:pre-tasks="formData.preTasks"
            :task-list-data="taskListData"
            :selected-tasks="formData.task_list"
            :controller-name="formData.controller_name"
            :resource-name="formData.resource_name"
            :task-options="formData.task_options"
            :current-setting-task-id="currentSettingTaskId"
            @update:tasks="handleTasksUpdate"
            @update:selected-tasks="handleSelectedTasksUpdate"
            @config="openTaskSettings"
          />
        </div>
      </div>

      <!-- Footer -->
      <footer
        class="border-[var(--divider-color)] flex shrink-0 items-center justify-end border-t px-4 py-3 sm:px-5"
      >
        <NSpace justify="end">
          <NButton quaternary @click="handleCancel">
            {{ t("common.cancel") }}
          </NButton>
          <NButton type="primary" :loading="loading" :disabled="loading" @click="handleSave">
            {{ t("common.save") }}
          </NButton>
        </NSpace>
      </footer>
    </div>
  </NModal>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch } from "vue"
import { useI18n } from "vue-i18n"
import { NButton, NIcon, NInput, NInputNumber, NModal, NSelect, NSpace, NSwitch } from "naive-ui"
import {
  CalendarNumberOutline,
  CalendarOutline,
  CloseOutline,
  CodeSlashOutline,
  FolderOpenOutline,
  GameControllerOutline,
  HardwareChipOutline,
  InformationCircleOutline,
  ListOutline,
  MoonOutline,
  PhonePortraitOutline,
  TextOutline,
  TimeOutline,
  TimerOutline,
} from "@vicons/ionicons5"
import {
  useInterfaceStore,
  useSchedulerStore,
  useSettingsStore,
  useTaskConfigStore,
} from "@/stores"
import type { TaskListItem } from "@/types/taskConfigModel"
import SchedulerTaskDialogContentTabs from "@/components/settings/dialogs/SchedulerTaskDialogContentTabs.vue"
import SchedulerTaskDialogSectionNav from "@/components/settings/dialogs/SchedulerTaskDialogSectionNav.vue"
import SchedulerTaskDialogTriggerType from "@/components/settings/dialogs/SchedulerTaskDialogTriggerType.vue"
import { customDeviceAddressSchema } from "@/schemas/device"
import { schedulerTaskFormSchema } from "@/schemas/scheduler"
import { resolveInterfaceText } from "@/utils/interface/content"
import { getDevices, getResource, postCustomDevice } from "@/services/api"
import type { ConnectableDevice, DeviceControllerType } from "@/services/api"
import { buildDeviceLabel } from "@/utils/panel/device"
import { checkNativeEligibility } from "@/schemas/cron"
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
import { useViewport } from "@/utils/viewport/useViewport"

interface Props {
  show: boolean
  task?: ScheduledTask | null
}

interface Emits {
  (e: "update:show", value: boolean): void
  (e: "saved"): void
}

type DialogSection = "basic" | "schedule" | "environment" | "content"

const { show, task } = defineProps<Props>()
const emit = defineEmits<Emits>()

const { t, locale } = useI18n()
const schedulerStore = useSchedulerStore()
const configStore = useTaskConfigStore()
const interfaceStore = useInterfaceStore()
const settingsStore = useSettingsStore()

const loading = ref(false)

const { isMobile, width: viewportWidth } = useViewport()

/** Keep the card within the viewport while retaining the desktop content-driven width. */
const dialogBoxStyle = computed(() => {
  if (isMobile.value) {
    return { width: "calc(100vw - 32px)", maxWidth: "calc(100vw - 32px)" }
  }
  const w = Math.min(Math.round(viewportWidth.value * 0.72), 960)
  return { width: `${w}px`, maxWidth: "none" }
})

const activeSection = ref<DialogSection>("basic")
const activeTab = ref<"task-list" | "task-settings" | "pre-tasks">("task-list")
const currentSettingTaskId = ref<string | null>(null)
const suppressFormInit = ref(false)
const wakeupEnabled = ref(false)

const availableDevices = ref<ConnectableDevice[]>([])
const availableResources = ref<Array<{ name: string; label?: string; controller?: string[] }>>([])
const loadingDevices = ref(false)
const loadingResources = ref(false)

const sections = computed(() => [
  {
    id: "basic" as const,
    label: t("settings.scheduler.dialog.sections.basic"),
    icon: InformationCircleOutline,
  },
  {
    id: "schedule" as const,
    label: t("settings.scheduler.dialog.sections.schedule"),
    icon: TimeOutline,
  },
  {
    id: "environment" as const,
    label: t("settings.scheduler.dialog.sections.environment"),
    icon: HardwareChipOutline,
  },
  {
    id: "content" as const,
    label: t("settings.scheduler.dialog.sections.content"),
    icon: ListOutline,
  },
])

const triggerOptions = computed(() => [
  {
    value: "cron" as const,
    label: t("settings.scheduler.dialog.cronExpression"),
    icon: CodeSlashOutline,
  },
  {
    value: "date" as const,
    label: t("settings.scheduler.dialog.specificTime"),
    icon: CalendarNumberOutline,
  },
  {
    value: "interval" as const,
    label: t("settings.scheduler.dialog.intervalExecution"),
    icon: TimerOutline,
  },
])

function isDeviceControllerType(type: string): type is DeviceControllerType {
  return type === "Adb" || type === "Win32" || type === "Gamepad" || type === "PlayCover"
}

/** Convert datetime-local / ISO string to ISO, or "" if empty/invalid. */
function toIsoOrEmpty(value: string): string {
  if (!value) return ""
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ""
  return d.toISOString()
}

/** Format ISO string for datetime-local input; "" if missing/invalid. */
function toDatetimeLocalValue(iso: string | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
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
const dateConfigLocal = computed(() => toDatetimeLocalValue(dateConfig.value.run_date))
const intervalConfig = computed<IntervalTriggerConfig>(() => {
  const config = formData.value.trigger_config
  return config.type === "interval" ? config : { type: "interval" }
})
const intervalStartLocal = computed(() => toDatetimeLocalValue(intervalConfig.value.start_date))
const intervalEndLocal = computed(() => toDatetimeLocalValue(intervalConfig.value.end_date))

type SchedulerTaskFormData = Omit<ScheduledTaskCreate, "wakeup_enabled">

const formData = ref<SchedulerTaskFormData>(initFormData(task))
const taskListData = ref<TaskListItem[]>([])

const triggerType = computed(() => formData.value.trigger_config.type)
const isCronNativeEligible = computed(() => {
  const config = formData.value.trigger_config
  return config.type === "cron" && checkNativeEligibility(config.cron)
})

watch(
  () => show,
  (open, previousOpen) => {
    if (open) {
      activeSection.value = "basic"
    } else if (previousOpen) {
      resetForm()
    }
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

// cron 从合格变为不合格时同步清空唤醒开关，避免隐藏值随提交被静默屏蔽
watch(isCronNativeEligible, (eligible) => {
  if (!eligible) {
    wakeupEnabled.value = false
  }
})

watch(
  () => formData.value.controller_name,
  (newVal, oldVal) => {
    const controller = interfaceStore.interface?.controller?.find((item) => item.name === newVal)
    const type = controller?.type

    if (!suppressFormInit.value && oldVal != null && oldVal !== newVal) {
      formData.value.device = null
      formData.value.resource_name = null
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
  activeSection.value = "basic"
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

function initFormData(task?: ScheduledTask | null): SchedulerTaskFormData {
  wakeupEnabled.value = task ? (task.wakeup_enabled ?? false) : false
  if (task) {
    const task_list = configStore.normalizeTaskIds(task.task_list)
    return {
      name: task.name,
      description: task.description || "",
      enabled: task.enabled,
      trigger_config: getTriggerConfigByType(task.trigger_config.type, task.trigger_config),
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
    trigger_config: getTriggerConfigByType("cron"),
    task_list: [],
    task_options: configStore.buildOptionsForTasks([]),
    preTasks: [],
    controller_name: null,
    device: null,
    resource_name: null,
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

function setTriggerType(newType: TriggerType) {
  formData.value.trigger_config = getTriggerConfigByType(newType)
  if (newType !== "cron") {
    wakeupEnabled.value = false
  }
}

function handleTriggerTypeChange(value: string | number) {
  if (value === "cron" || value === "date" || value === "interval") {
    setTriggerType(value)
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
  activeSection.value = "content"
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

/** Persist a user-typed device address as a custom device and select it. */
async function handleCustomDeviceCreate(rawAddress: string) {
  const controllerName = formData.value.controller_name
  const controllerType = selectedControllerType.value
  if (!controllerName || !controllerType || !isDeviceControllerType(controllerType)) return

  const parseResult = customDeviceAddressSchema.safeParse({
    type: controllerType,
    address: rawAddress,
  })
  if (!parseResult.success) {
    showGlobalMessage("error", t("settings.scheduler.rules.invalidAddress"))
    return
  }
  const address = parseResult.data.address

  const [result, err] = await tryCatch(() =>
    postCustomDevice({
      controller_name: controllerName,
      type: controllerType,
      address,
    }),
  )
  if (err || !result?.success) {
    showGlobalMessage("error", result?.message || t("settings.scheduler.dialog.saveFail"))
    return
  }

  // Refresh device list so the new device appears, then select it
  await fetchDevices(controllerName)
  // 用户在请求期间可能已切换控制器：仅当当前选择仍匹配才写入地址，避免把旧地址落到别的控制器上。
  const currentControllerName = formData.value.controller_name
  const currentControllerType = selectedControllerType.value
  if (currentControllerName !== controllerName || currentControllerType !== controllerType) {
    return
  }
  selectedDeviceAddress.value = address
}

function handleDeviceAddressUpdate(value: string | null) {
  if (value && !deviceAddressOptions.value.some((option) => option.value === value)) {
    void handleCustomDeviceCreate(value)
    return
  }
  selectedDeviceAddress.value = value
}

async function handleSave() {
  const taskPayload = {
    ...formData.value,
    wakeup_enabled:
      triggerType.value === "cron" && isCronNativeEligible.value ? wakeupEnabled.value : false,
    ...configStore.buildExecutionPayload(formData.value.task_list, formData.value.task_options),
    preTasks: formData.value.preTasks ?? [],
  }

  const parseResult = schedulerTaskFormSchema.safeParse(taskPayload)
  if (!parseResult.success) {
    const firstIssue = parseResult.error.issues[0]
    const path = firstIssue.path.join(".")
    // Route to correct section based on issue path
    if (path.startsWith("name")) {
      activeSection.value = "basic"
      showGlobalMessage("error", t("settings.scheduler.rules.nameRequired"))
      return
    }
    if (path.startsWith("trigger_config.cron")) {
      activeSection.value = "schedule"
      showGlobalMessage("error", t("settings.scheduler.rules.cronInvalid"))
      return
    }
    if (path.startsWith("trigger_config.run_date")) {
      activeSection.value = "schedule"
      const msg = firstIssue.message.includes("future")
        ? t("settings.scheduler.rules.dateInPast")
        : t("settings.scheduler.rules.dateRequired")
      showGlobalMessage("error", msg)
      return
    }
    if (!path || path.startsWith("trigger_config")) {
      activeSection.value = "schedule"
      showGlobalMessage("error", t("settings.scheduler.rules.intervalRequired"))
      return
    }
    if (path.startsWith("task_list")) {
      activeSection.value = "content"
      activeTab.value = "task-list"
      showGlobalMessage("error", t("settings.scheduler.rules.taskListRequired"))
      return
    }
    showGlobalMessage("error", firstIssue.message)
    return
  }

  const parsedTask = {
    ...parseResult.data,
    description: parseResult.data.description ?? undefined,
    preTasks: parseResult.data.preTasks.map((preTask) => ({
      ...preTask,
      id: preTask.id ?? crypto.randomUUID(),
    })),
  }

  loading.value = true
  const [savedTask, err] = await tryCatch(async () => {
    if (isEditMode.value && task) {
      const ok = await schedulerStore.updateTask(task.id, parsedTask)
      return ok ? task : null
    }
    return schedulerStore.createTask(parsedTask)
  })
  loading.value = false
  if (err || !savedTask) {
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
