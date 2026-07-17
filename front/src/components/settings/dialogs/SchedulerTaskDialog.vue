<template>
  <dialog
    ref="dialogRef"
    class="modal modal-bottom sm:modal-middle"
    aria-labelledby="scheduler-task-dialog-title"
    @close="onNativeClose"
  >
    <div
      class="modal-box flex h-[min(92dvh,720px)] w-full max-w-4xl flex-col p-0 sm:h-auto sm:max-h-[90vh]"
    >
      <!-- Header -->
      <header
        class="border-base-200 flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3 sm:px-5"
      >
        <div class="flex min-w-0 items-center gap-2">
          <Icon
            icon="mdi:calendar-clock"
            class="text-primary shrink-0 text-xl"
            aria-hidden="true"
          />
          <h3 id="scheduler-task-dialog-title" class="truncate text-base font-semibold sm:text-lg">
            {{
              isEditMode
                ? t("settings.scheduler.dialog.editTitle")
                : t("settings.scheduler.dialog.createTitle")
            }}
          </h3>
        </div>
        <button
          type="button"
          class="btn btn-ghost btn-sm btn-square shrink-0"
          :title="t('common.cancel')"
          :aria-label="t('common.cancel')"
          @click="handleCancel"
        >
          <Icon icon="mdi:close" class="text-lg" aria-hidden="true" />
        </button>
      </header>

      <!-- Body: section nav + scrollable content -->
      <div class="flex min-h-0 flex-1 flex-col md:flex-row">
        <!-- Section navigation -->
        <nav
          class="border-base-200 flex shrink-0 gap-1 overflow-x-auto border-b p-2 md:w-44 md:flex-col md:overflow-y-auto md:overflow-x-hidden md:border-r md:border-b-0 md:p-3"
          :aria-label="t('settings.scheduler.dialog.sections.nav')"
        >
          <button
            v-for="section in sections"
            :key="section.id"
            type="button"
            class="btn btn-sm h-auto min-h-0 shrink-0 justify-start gap-1 px-2 py-2 text-xs font-normal normal-case md:gap-2 md:px-3 md:text-sm"
            :class="activeSection === section.id ? 'btn-primary' : 'btn-ghost text-base-content/80'"
            :aria-current="activeSection === section.id ? 'page' : undefined"
            @click="activeSection = section.id"
          >
            <Icon
              :icon="section.icon"
              class="hidden shrink-0 text-base md:block"
              aria-hidden="true"
            />
            <span class="whitespace-nowrap">{{ section.label }}</span>
          </button>
        </nav>

        <!-- Scrollable content: flex+gap so section pieces space without extra wrappers -->
        <div
          class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5"
        >
          <!-- Basic info -->
          <fieldset v-if="activeSection === 'basic'" class="fieldset p-0">
            <legend class="fieldset-legend flex items-center gap-1.5">
              <Icon icon="mdi:form-textbox" class="text-base opacity-70" aria-hidden="true" />
              {{ t("settings.scheduler.dialog.taskName") }}
            </legend>
            <input
              v-model="formData.name"
              type="text"
              class="input input-bordered w-full"
              :placeholder="t('settings.scheduler.dialog.taskNamePlaceholder')"
              autocomplete="off"
            />
          </fieldset>

          <fieldset v-if="activeSection === 'basic'" class="fieldset p-0">
            <legend class="fieldset-legend flex items-center gap-1.5">
              <Icon icon="mdi:text" class="text-base opacity-70" aria-hidden="true" />
              {{ t("settings.scheduler.dialog.taskDesc") }}
            </legend>
            <textarea
              v-model="formData.description"
              class="textarea textarea-bordered w-full min-h-20"
              :placeholder="t('settings.scheduler.dialog.taskDescPlaceholder')"
              rows="3"
            />
          </fieldset>

          <!-- Schedule: trigger type -->
          <fieldset v-if="activeSection === 'schedule'" class="fieldset p-0">
            <legend class="fieldset-legend flex items-center gap-1.5">
              <Icon icon="mdi:lightning-bolt" class="text-base opacity-70" aria-hidden="true" />
              {{ t("settings.scheduler.dialog.triggerType") }}
            </legend>
            <div class="flex flex-wrap gap-2">
              <label
                v-for="option in triggerOptions"
                :key="option.value"
                class="border-base-300 hover:border-primary/40 has-[:checked]:border-primary has-[:checked]:bg-primary/5 flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 transition-colors"
              >
                <input
                  v-model="formData.trigger_type"
                  type="radio"
                  class="radio radio-primary radio-sm"
                  :value="option.value"
                />
                <Icon :icon="option.icon" class="text-base opacity-70" aria-hidden="true" />
                <span class="text-sm">{{ option.label }}</span>
              </label>
            </div>
          </fieldset>

          <!-- Schedule: cron -->
          <fieldset
            v-if="activeSection === 'schedule' && formData.trigger_type === 'cron'"
            class="fieldset p-0"
          >
            <legend class="fieldset-legend">
              {{ t("settings.scheduler.dialog.cronExpression") }}
            </legend>
            <input
              :value="cronConfig.cron"
              type="text"
              class="input input-bordered w-full font-mono text-sm"
              :placeholder="t('settings.scheduler.dialog.cronPlaceholder')"
              spellcheck="false"
              @input="updateTriggerConfig({ cron: getInputValue($event) })"
            />
          </fieldset>
          <div
            v-if="activeSection === 'schedule' && formData.trigger_type === 'cron'"
            class="flex flex-wrap gap-2"
          >
            <span class="text-base-content/50 self-center text-xs">
              {{ t("settings.scheduler.dialog.quickSelect") }}
            </span>
            <button type="button" class="btn btn-outline btn-xs" @click="setCronPreset('daily')">
              {{ t("settings.scheduler.dialog.presets.daily") }}
            </button>
            <button type="button" class="btn btn-outline btn-xs" @click="setCronPreset('daily9am')">
              {{ t("settings.scheduler.dialog.presets.daily9am") }}
            </button>
            <button type="button" class="btn btn-outline btn-xs" @click="setCronPreset('weekly')">
              {{ t("settings.scheduler.dialog.presets.weekly") }}
            </button>
            <button type="button" class="btn btn-outline btn-xs" @click="setCronPreset('hourly')">
              {{ t("settings.scheduler.dialog.presets.hourly") }}
            </button>
          </div>

          <!-- Schedule: date -->
          <fieldset
            v-if="activeSection === 'schedule' && formData.trigger_type === 'date'"
            class="fieldset p-0"
          >
            <legend class="fieldset-legend">
              {{ t("settings.scheduler.dialog.executionTime") }}
            </legend>
            <input
              type="datetime-local"
              class="input input-bordered w-full max-w-xs"
              :value="dateConfigLocal"
              @input="
                updateTriggerConfig({
                  run_date: toIsoOrEmpty(getInputValue($event)),
                })
              "
            />
          </fieldset>

          <!-- Schedule: interval duration -->
          <fieldset
            v-if="activeSection === 'schedule' && formData.trigger_type === 'interval'"
            class="fieldset p-0"
          >
            <legend class="fieldset-legend">
              {{ t("settings.scheduler.dialog.intervalTime") }}
            </legend>
            <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <label class="flex flex-col gap-1">
                <span class="text-xs opacity-60">{{ t("settings.scheduler.formatter.week") }}</span>
                <input
                  :value="intervalConfig.weeks"
                  type="number"
                  class="input input-bordered w-full"
                  min="0"
                  @input="
                    updateTriggerConfig({
                      weeks: Number(getInputValue($event)) || 0,
                    })
                  "
                />
              </label>
              <label class="flex flex-col gap-1">
                <span class="text-xs opacity-60">{{ t("settings.scheduler.formatter.day") }}</span>
                <input
                  :value="intervalConfig.days"
                  type="number"
                  class="input input-bordered w-full"
                  min="0"
                  @input="
                    updateTriggerConfig({
                      days: Number(getInputValue($event)) || 0,
                    })
                  "
                />
              </label>
              <label class="flex flex-col gap-1">
                <span class="text-xs opacity-60">{{ t("settings.scheduler.formatter.hour") }}</span>
                <input
                  :value="intervalConfig.hours"
                  type="number"
                  class="input input-bordered w-full"
                  min="0"
                  @input="
                    updateTriggerConfig({
                      hours: Number(getInputValue($event)) || 0,
                    })
                  "
                />
              </label>
              <label class="flex flex-col gap-1">
                <span class="text-xs opacity-60">{{
                  t("settings.scheduler.formatter.minute")
                }}</span>
                <input
                  :value="intervalConfig.minutes"
                  type="number"
                  class="input input-bordered w-full"
                  min="0"
                  @input="
                    updateTriggerConfig({
                      minutes: Number(getInputValue($event)) || 0,
                    })
                  "
                />
              </label>
              <label class="flex flex-col gap-1 col-span-2 sm:col-span-1">
                <span class="text-xs opacity-60">{{
                  t("settings.scheduler.formatter.second")
                }}</span>
                <input
                  :value="intervalConfig.seconds"
                  type="number"
                  class="input input-bordered w-full"
                  min="0"
                  @input="
                    updateTriggerConfig({
                      seconds: Number(getInputValue($event)) || 0,
                    })
                  "
                />
              </label>
            </div>
          </fieldset>

          <!-- Schedule: interval start/end -->
          <div
            v-if="activeSection === 'schedule' && formData.trigger_type === 'interval'"
            class="grid grid-cols-1 gap-3 sm:grid-cols-2"
          >
            <fieldset class="fieldset p-0">
              <legend class="fieldset-legend">
                {{ t("settings.scheduler.dialog.startTime") }}
              </legend>
              <input
                type="datetime-local"
                class="input input-bordered w-full"
                :value="intervalStartLocal"
                @input="
                  updateTriggerConfig({
                    start_date: toIsoOrEmpty(getInputValue($event)) || undefined,
                  })
                "
              />
            </fieldset>
            <fieldset class="fieldset p-0">
              <legend class="fieldset-legend">
                {{ t("settings.scheduler.dialog.endTime") }}
              </legend>
              <input
                type="datetime-local"
                class="input input-bordered w-full"
                :value="intervalEndLocal"
                @input="
                  updateTriggerConfig({
                    end_date: toIsoOrEmpty(getInputValue($event)) || undefined,
                  })
                "
              />
            </fieldset>
          </div>

          <!-- Environment -->
          <fieldset v-if="activeSection === 'environment'" class="fieldset p-0">
            <legend class="fieldset-legend flex items-center gap-1.5">
              <Icon icon="mdi:gamepad-variant" class="text-base opacity-70" aria-hidden="true" />
              {{ t("settings.scheduler.dialog.controller") }}
            </legend>
            <select
              v-model="formData.controller_name"
              class="select select-bordered w-full"
              :disabled="loadingDevices"
            >
              <option value="">{{ t("panel.selectDeviceType") }}</option>
              <option v-for="opt in deviceControllerOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </fieldset>

          <fieldset v-if="activeSection === 'environment'" class="fieldset p-0">
            <legend class="fieldset-legend flex items-center gap-1.5">
              <Icon icon="mdi:cellphone-link" class="text-base opacity-70" aria-hidden="true" />
              {{ t("settings.scheduler.dialog.deviceAddress") }}
            </legend>
            <input
              v-if="isPlayCover"
              v-model="selectedDeviceAddress"
              type="text"
              class="input input-bordered w-full"
              :placeholder="t('panel.playcoverAddress')"
              :disabled="!formData.controller_name"
            />
            <select
              v-else
              v-model="selectedDeviceAddress"
              class="select select-bordered w-full"
              :disabled="!formData.controller_name || loadingDevices"
            >
              <option value="">{{ t("panel.selectDevice") }}</option>
              <option v-for="opt in deviceAddressOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </fieldset>

          <fieldset v-if="activeSection === 'environment'" class="fieldset p-0">
            <legend class="fieldset-legend flex items-center gap-1.5">
              <Icon icon="mdi:folder-cog" class="text-base opacity-70" aria-hidden="true" />
              {{ t("settings.scheduler.dialog.resource") }}
            </legend>
            <select
              v-model="formData.resource_name"
              class="select select-bordered w-full"
              :disabled="!formData.controller_name || loadingResources"
            >
              <option value="">{{ t("panel.selectResource") }}</option>
              <option v-for="opt in resourceOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </fieldset>

          <!-- System Scheduling (user-level OS wakeup) -->
          <fieldset v-if="activeSection === 'system'" class="fieldset p-0">
            <legend class="fieldset-legend flex items-center gap-1.5">
              <Icon icon="mdi:monitor-shimmer" class="text-base opacity-70" aria-hidden="true" />
              {{ t("settings.scheduler.dialog.systemScheduling") }}
            </legend>

            <label class="flex cursor-pointer items-center gap-3">
              <input
                v-model="systemSchedulingEnabled"
                type="checkbox"
                class="toggle toggle-primary"
              />
              <span class="text-sm">{{
                t("settings.scheduler.dialog.enableSystemScheduling")
              }}</span>
            </label>
          </fieldset>

          <!-- Content: tasks -->
          <div v-if="activeSection === 'content'" class="flex min-h-0 flex-col gap-3">
            <div role="tablist" class="tabs tabs-box tabs-sm w-full flex-nowrap overflow-x-auto">
              <button
                type="button"
                role="tab"
                class="tab gap-1.5"
                :class="{ 'tab-active': activeTab === 'pre-tasks' }"
                :aria-selected="activeTab === 'pre-tasks'"
                @click="activeTab = 'pre-tasks'"
              >
                <Icon icon="mdi:console" class="text-base" aria-hidden="true" />
                <span class="whitespace-nowrap">{{
                  t("settings.scheduler.dialog.tab.preTasks")
                }}</span>
              </button>
              <button
                type="button"
                role="tab"
                class="tab gap-1.5"
                :class="{ 'tab-active': activeTab === 'task-list' }"
                :aria-selected="activeTab === 'task-list'"
                @click="activeTab = 'task-list'"
              >
                <Icon icon="mdi:playlist-check" class="text-base" aria-hidden="true" />
                <span class="whitespace-nowrap">{{
                  t("settings.scheduler.dialog.tab.taskList")
                }}</span>
              </button>
              <button
                type="button"
                role="tab"
                class="tab gap-1.5"
                :class="{ 'tab-active': activeTab === 'task-settings' }"
                :aria-selected="activeTab === 'task-settings'"
                @click="activeTab = 'task-settings'"
              >
                <Icon icon="mdi:tune" class="text-base" aria-hidden="true" />
                <span class="whitespace-nowrap">{{
                  t("settings.scheduler.dialog.tab.taskSettings")
                }}</span>
              </button>
            </div>

            <div class="min-h-48">
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
        </div>
      </div>

      <!-- Footer -->
      <footer
        class="border-base-200 flex shrink-0 items-center justify-end gap-2 border-t px-4 py-3 sm:px-5"
      >
        <button type="button" class="btn btn-ghost" @click="handleCancel">
          {{ t("common.cancel") }}
        </button>
        <button type="button" class="btn btn-primary" :disabled="loading" @click="handleSave">
          <Icon
            v-if="loading"
            icon="mdi:loading"
            class="mr-1 animate-spin text-lg"
            aria-hidden="true"
          />
          {{ t("common.save") }}
        </button>
      </footer>
    </div>

    <form method="dialog" class="modal-backdrop">
      <button type="submit">{{ t("common.cancel") }}</button>
    </form>
  </dialog>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, useTemplateRef } from "vue"
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

type DialogSection = "basic" | "schedule" | "environment" | "system" | "content"

const { show, task } = defineProps<Props>()
const emit = defineEmits<Emits>()

const { t, locale } = useI18n()
const schedulerStore = useSchedulerStore()
const configStore = useTaskConfigStore()
const interfaceStore = useInterfaceStore()
const settingsStore = useSettingsStore()

const dialogRef = useTemplateRef<HTMLDialogElement>("dialogRef")
const loading = ref(false)
const closingFromUi = ref(false)

const activeSection = ref<DialogSection>("basic")
const activeTab = ref<"task-list" | "task-settings" | "pre-tasks">("task-list")
const currentSettingTaskId = ref<string | null>(null)
const suppressFormInit = ref(false)

const availableDevices = ref<ConnectableDevice[]>([])
const availableResources = ref<Array<{ name: string; label?: string; controller?: string[] }>>([])
const loadingDevices = ref(false)
const loadingResources = ref(false)

const systemSchedulingEnabled = ref(false)

const sections = computed(() => [
  {
    id: "basic" as const,
    label: t("settings.scheduler.dialog.sections.basic"),
    icon: "mdi:information-outline",
  },
  {
    id: "schedule" as const,
    label: t("settings.scheduler.dialog.sections.schedule"),
    icon: "mdi:clock-outline",
  },
  {
    id: "environment" as const,
    label: t("settings.scheduler.dialog.sections.environment"),
    icon: "mdi:devices",
  },
  {
    id: "system" as const,
    label: t("settings.scheduler.dialog.systemScheduling"),
    icon: "mdi:monitor-shimmer",
  },
  {
    id: "content" as const,
    label: t("settings.scheduler.dialog.sections.content"),
    icon: "mdi:playlist-check",
  },
])

const triggerOptions = computed(() => [
  {
    value: "cron" as const,
    label: t("settings.scheduler.dialog.cronExpression"),
    icon: "mdi:code-braces",
  },
  {
    value: "date" as const,
    label: t("settings.scheduler.dialog.specificTime"),
    icon: "mdi:calendar-month",
  },
  {
    value: "interval" as const,
    label: t("settings.scheduler.dialog.intervalExecution"),
    icon: "mdi:timer-outline",
  },
])

function isDeviceControllerType(type: string): type is DeviceControllerType {
  return type === "Adb" || type === "Win32" || type === "Gamepad" || type === "PlayCover"
}

function getInputValue(event: Event): string {
  const target = event.target
  return target instanceof HTMLInputElement ? target.value : ""
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

const formData = ref<ScheduledTaskCreate>(initFormData(task))
const taskListData = ref<TaskListItem[]>([])

function syncDialogVisibility(open: boolean) {
  const el = dialogRef.value
  if (!el) {
    return
  }
  if (open) {
    if (!el.open) {
      el.showModal()
    }
    return
  }
  if (el.open) {
    el.close()
  }
}

watch(
  () => show,
  async (open) => {
    await nextTick()
    syncDialogVisibility(open)
    if (!open) {
      return
    }
    activeSection.value = "basic"
    systemSchedulingEnabled.value = false
    if (task) {
      // Treat legacy "system" and current "user" scopes as enabled (user-only wakeup).
      // Backend may still return historical "system"; any non-null scope means enabled.
      if (task.system_scope) {
        systemSchedulingEnabled.value = true
        return
      }
      const status = schedulerStore.getSystemStatus(task.id)
      if (status && (status.state === "active" || status.state === "pending_register")) {
        systemSchedulingEnabled.value = true
      }
    }
  },
)

onMounted(() => {
  if (show) {
    syncDialogVisibility(true)
  }
})

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
  systemSchedulingEnabled.value = false
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

function validateName(): boolean {
  const name = formData.value.name.trim()
  if (!name) {
    showGlobalMessage("error", t("settings.scheduler.rules.nameRequired"))
    activeSection.value = "basic"
    return false
  }
  if (name.length > 100) {
    showGlobalMessage("error", t("settings.scheduler.rules.nameLength"))
    activeSection.value = "basic"
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
    activeSection.value = "schedule"
    return false
  }
  const pattern =
    /^(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)$/
  if (!pattern.test(config.cron)) {
    showGlobalMessage("error", t("settings.scheduler.rules.cronInvalid"))
    activeSection.value = "schedule"
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
    activeSection.value = "schedule"
    return false
  }
  if (new Date(config.run_date).getTime() < Date.now()) {
    showGlobalMessage("error", t("settings.scheduler.rules.dateInPast"))
    activeSection.value = "schedule"
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
    activeSection.value = "schedule"
    return false
  }
  if (config.start_date && config.end_date) {
    const startAt = new Date(config.start_date).getTime()
    const endAt = new Date(config.end_date).getTime()
    if (endAt < startAt) {
      showGlobalMessage("error", t("settings.scheduler.rules.endBeforeStart"))
      activeSection.value = "schedule"
      return false
    }
  }
  return true
}

function validateTaskList(): boolean {
  if (formData.value.task_list.length === 0) {
    showGlobalMessage("error", t("settings.scheduler.rules.taskListRequired"))
    activeSection.value = "content"
    activeTab.value = "task-list"
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

async function saveTaskPayload(): Promise<{ taskId: string; success: boolean }> {
  const taskPayload = {
    ...formData.value,
    ...configStore.buildExecutionPayload(formData.value.task_list, formData.value.task_options),
    preTasks: formData.value.preTasks ?? [],
    system_scope: systemSchedulingEnabled.value ? "user" : null,
  }

  if (isEditMode.value && task) {
    const success = await schedulerStore.updateTask(task.id, taskPayload)
    if (!success) {
      return { taskId: "", success: false }
    }
    return { taskId: task.id, success: true }
  }

  const createdTask = await schedulerStore.createTask(taskPayload)
  if (!createdTask) {
    return { taskId: "", success: false }
  }
  return { taskId: createdTask.id, success: true }
}

async function handleSave() {
  if (!validateForm()) {
    return
  }

  loading.value = true
  const { success } = await saveTaskPayload()
  loading.value = false

  if (!success) {
    showGlobalMessage("error", schedulerStore.error || t("settings.scheduler.dialog.saveFail"))
    return
  }

  showGlobalMessage(
    "success",
    isEditMode.value
      ? t("settings.scheduler.dialog.taskUpdated")
      : t("settings.scheduler.dialog.taskCreated"),
  )
  closingFromUi.value = true
  showDialog.value = false
  emit("saved")
  resetForm()
}

function handleCancel() {
  closingFromUi.value = true
  showDialog.value = false
  resetForm()
}

function onNativeClose() {
  if (closingFromUi.value) {
    closingFromUi.value = false
    return
  }
  // ESC / backdrop closed the dialog
  if (show) {
    emit("update:show", false)
  }
  resetForm()
}
</script>
