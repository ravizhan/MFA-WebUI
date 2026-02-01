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
            @update:value="updateCronConfig"
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
            @update:value="updateDateConfig"
            type="datetime"
            :placeholder="t('settings.scheduler.dialog.selectTime')"
            style="width: 100%"
          />
        </n-form-item>
      </template>

      <!-- Interval 触发器 -->
      <template v-if="formData.trigger_type === 'interval'">
        <n-form-item :label="t('settings.scheduler.dialog.intervalTime')" path="trigger_config">
          <n-flex>
            <n-input-number
              :value="intervalConfig.hours"
              @update:value="updateIntervalHours"
              :min="0"
              style="width: 45%"
            >
              <template #suffix>{{ t("settings.scheduler.formatter.hour") }}</template>
            </n-input-number>
            <n-input-number
              :value="intervalConfig.minutes"
              @update:value="updateIntervalMinutes"
              :min="0"
              style="width: 45%"
            >
              <template #suffix>{{ t("settings.scheduler.formatter.minute") }}</template>
            </n-input-number>
          </n-flex>
        </n-form-item>
      </template>

      <n-tabs v-model:value="activeTab" type="segment" animated>
        <!-- Tab 1: 任务列表 -->
        <n-tab-pane name="task-list" :tab="t('settings.scheduler.dialog.tab.taskList')">
          <n-scrollbar trigger="none" class="max-h-65 !rounded-[12px]">
            <n-list hoverable bordered>
              <n-list-item v-for="task in availableTasks" :key="task.id">
                <n-checkbox
                  size="large"
                  :label="task.name"
                  :checked="isTaskSelected(task.id)"
                  @update:checked="(v: boolean) => toggleTaskSelection(task.id, v)"
                />
                <template #suffix>
                  <n-button quaternary circle @click="openTaskSettings(task.id)">
                    <template #icon>
                      <n-icon><div class="i-mdi-cog-outline"></div></n-icon>
                    </template>
                  </n-button>
                </template>
              </n-list-item>
            </n-list>
          </n-scrollbar>
        </n-tab-pane>

        <!-- Tab 2: 任务设置 -->
        <n-tab-pane name="task-settings" :tab="t('settings.scheduler.dialog.tab.taskSettings')">
          <div v-if="currentSettingTaskName" class="text-center">
            <n-tag type="info" size="large">
              {{ t("settings.scheduler.dialog.currentSetting") }}{{ currentSettingTaskName }}
            </n-tag>
          </div>
          <n-scrollbar trigger="none" class="max-h-65 !rounded-[12px]">
            <div v-if="currentSettingTaskId === null">
              <n-empty :description="t('settings.scheduler.dialog.selectTaskTip')" />
            </div>
            <div v-else>
              <n-list v-if="currentTaskOptions.length > 0" hoverable>
                <OptionItem
                  v-for="optName in currentTaskOptions"
                  :key="optName"
                  :name="optName"
                  :options="formData.task_options"
                />
              </n-list>
              <n-empty v-else :description="t('settings.scheduler.dialog.noOptions')" />
            </div>
          </n-scrollbar>
        </n-tab-pane>
      </n-tabs>
    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="handleCancel">{{
          t("settings.scheduler.dialog.actions.cancel")
        }}</n-button>
        <n-button type="primary" @click="handleSave" :loading="loading">{{
          t("settings.scheduler.dialog.actions.save")
        }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue"
import { useMessage, type FormInst, type FormRules } from "naive-ui"
import { useI18n } from "vue-i18n"
import { useSchedulerStore } from "../stores/scheduler"
import { useInterfaceStore } from "../stores/interface"
import OptionItem from "./OptionItem.vue"
import type {
  ScheduledTask,
  ScheduledTaskCreate,
  TriggerConfig,
  CronTriggerConfig,
  DateTriggerConfig,
  IntervalTriggerConfig,
} from "../types/scheduler"

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
const { t } = useI18n()
const schedulerStore = useSchedulerStore()
const interfaceStore = useInterfaceStore()

const formRef = ref<FormInst | null>(null)
const loading = ref(false)

const activeTab = ref<"task-list" | "task-settings">("task-list")
const currentSettingTaskId = ref<string | null>(null)

const showDialog = computed({
  get: () => props.show,
  set: (value) => emit("update:show", value),
})

const isEditMode = computed(() => !!props.task)
const availableTasks = computed(() => interfaceStore.getTaskList)

// 获取完整的任务信息（包含 option）
const getFullTask = (taskId: string) => {
  return interfaceStore.interface?.task?.find((t) => t.entry === taskId)
}

const currentSettingTaskName = computed(() => {
  if (!currentSettingTaskId.value) return ""
  const task = availableTasks.value.find((t) => t.id === currentSettingTaskId.value)
  return task?.name || ""
})

const currentTaskOptions = computed(() => {
  if (!currentSettingTaskId.value) return []
  const task = getFullTask(currentSettingTaskId.value)
  return task?.option || []
})

// 触发器配置的 computed 属性
const cronConfig = computed(() => formData.value.trigger_config as CronTriggerConfig)
const dateConfig = computed(() => formData.value.trigger_config as DateTriggerConfig)
const dateConfigTimestamp = computed(() =>
  dateConfig.value.run_date ? new Date(dateConfig.value.run_date).getTime() : null,
)
const intervalConfig = computed(() => formData.value.trigger_config as IntervalTriggerConfig)

// 检查任务是否被选中
const isTaskSelected = (taskId: string) => {
  const task = availableTasks.value.find((t) => t.id === taskId)
  return task ? formData.value.task_list.includes(task.name) : false
}

const formData = ref<ScheduledTaskCreate>(initFormData())

const formRules = computed<FormRules>(() => ({
  name: [
    { required: true, message: t("settings.scheduler.rules.nameRequired"), trigger: "blur" },
    { min: 1, max: 100, message: t("settings.scheduler.rules.nameLength"), trigger: "blur" },
  ],
  trigger_config: {
    cron: [
      { required: true, message: t("settings.scheduler.rules.cronRequired"), trigger: "blur" },
      {
        pattern:
          /^(\*|[0-9\-\*,\/]+)\s+(\*|[0-9\-\*,\/]+)\s+(\*|[0-9\-\*,\/]+)\s+(\*|[0-9\-\*,\/]+)\s+(\*|[0-9\-\*,\/]+)$/,
        message: t("settings.scheduler.rules.cronInvalid"),
        trigger: "blur",
      },
    ],
  },
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
    if (task) {
      formData.value = {
        name: task.name,
        description: task.description || "",
        enabled: task.enabled,
        trigger_type: task.trigger_type,
        trigger_config: { ...task.trigger_config },
        task_list: [...task.task_list],
        task_options: { ...task.task_options },
      }
    } else {
      resetForm()
    }
  },
)

function resetForm() {
  formData.value = initFormData()
  currentSettingTaskId.value = null
  activeTab.value = "task-list"
}

// 初始化表单数据
function initFormData(): ScheduledTaskCreate {
  return {
    name: "",
    description: "",
    enabled: true,
    trigger_type: "cron",
    trigger_config: getTriggerConfigByType("cron"),
    task_list: [],
    task_options: {},
  }
}

// 根据类型获取触发器配置
function getTriggerConfigByType(type: string): TriggerConfig {
  switch (type) {
    case "cron":
      return { type: "cron", cron: "0 0 * * *" } as CronTriggerConfig
    case "date":
      return { type: "date", run_date: new Date().toISOString() } as DateTriggerConfig
    case "interval":
      return { type: "interval", hours: 1, minutes: 0 } as IntervalTriggerConfig
    default:
      return { type: "cron", cron: "0 0 * * *" } as CronTriggerConfig
  }
}

// 更新触发器配置的方法
function updateCronConfig(value: string) {
  formData.value.trigger_config = { type: "cron", cron: value } as CronTriggerConfig
}

function updateDateConfig(value: number | null) {
  formData.value.trigger_config = {
    type: "date",
    run_date: value ? new Date(value).toISOString() : new Date().toISOString(),
  } as DateTriggerConfig
}

function updateIntervalHours(value: number | null) {
  formData.value.trigger_config = {
    ...intervalConfig.value,
    hours: value || 0,
  } as IntervalTriggerConfig
}

function updateIntervalMinutes(value: number | null) {
  formData.value.trigger_config = {
    ...intervalConfig.value,
    minutes: value || 0,
  } as IntervalTriggerConfig
}

function setCronPreset(preset: string) {
  const presets: Record<string, string> = {
    daily: "0 0 * * *",
    daily9am: "0 9 * * *",
    weekly: "0 0 * * 1",
    hourly: "0 * * * *",
  }
  formData.value.trigger_config = { type: "cron", cron: presets[preset] } as CronTriggerConfig
}

function toggleTaskSelection(taskId: string, checked: boolean) {
  const task = availableTasks.value.find((t) => t.id === taskId)
  if (!task) return

  if (checked) {
    if (!formData.value.task_list.includes(task.name)) {
      formData.value.task_list.push(task.name)
    }
  } else {
    formData.value.task_list = formData.value.task_list.filter((name) => name !== task.name)
    if (currentSettingTaskId.value === taskId) {
      currentSettingTaskId.value = null
    }
  }
}

function openTaskSettings(taskId: string) {
  currentSettingTaskId.value = taskId
  activeTab.value = "task-settings"
  initTaskOptions(taskId)
}

// 初始化任务选项
function initTaskOptions(taskId: string) {
  const task = getFullTask(taskId)
  if (!task?.option) return

  for (const optionName of task.option) {
    if (formData.value.task_options[optionName]) continue

    const option = interfaceStore.interface?.option?.[optionName]
    if (!option) continue

    formData.value.task_options[optionName] = getOptionDefaultValue(option)
  }
}

// 获取选项默认值
function getOptionDefaultValue(option: any): string {
  switch (option.type) {
    case "select":
      return option.default_case || option.cases?.[0]?.name || ""
    case "switch":
      return option.cases?.[0]?.name || ""
    case "input":
      return option.inputs?.[0]?.default || ""
    default:
      return ""
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
    let success = false
    if (isEditMode.value && props.task) {
      success = await schedulerStore.updateTask(props.task.id, formData.value)
    } else {
      success = await schedulerStore.createTask(formData.value)
    }

    if (success) {
      message.success(
        isEditMode.value
          ? t("settings.scheduler.messages.successUpdate")
          : t("settings.scheduler.messages.successCreate"),
      )
      showDialog.value = false
      emit("saved")
      resetForm()
    } else {
      message.error(schedulerStore.error || t("settings.scheduler.messages.failSave"))
    }
  } catch (e) {
    message.error(t("settings.scheduler.messages.failRetry"))
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
