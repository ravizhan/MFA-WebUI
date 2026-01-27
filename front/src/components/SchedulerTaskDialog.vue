<template>
  <n-modal
    v-model:show="showDialog"
    preset="card"
    :title="isEditMode ? '编辑定时任务' : '新建定时任务'"
    class="xl:w-45% w-95"
  >
    <n-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-placement="left"
      label-width="100"
    >
      <n-form-item label="任务名称" path="name">
        <n-input v-model:value="formData.name" placeholder="请输入任务名称" />
      </n-form-item>

      <n-form-item label="任务描述" path="description">
        <n-input
          v-model:value="formData.description"
          type="textarea"
          placeholder="请输入任务描述"
          :autosize="{ minRows: 2, maxRows: 4 }"
        />
      </n-form-item>

      <n-form-item label="触发器类型" path="trigger_type">
        <n-radio-group v-model:value="formData.trigger_type">
          <n-radio value="cron">Cron 表达式</n-radio>
          <n-radio value="date">指定时间</n-radio>
          <n-radio value="interval">间隔执行</n-radio>
        </n-radio-group>
      </n-form-item>

      <!-- Cron 表达式编辑器 -->
      <template v-if="formData.trigger_type === 'cron'">
        <n-form-item label="Cron 表达式" path="trigger_config.cron">
          <n-input
            :value="cronConfig.cron"
            @update:value="updateCronConfig"
            placeholder="* * * * * (分 时 日 月 周)"
          />
        </n-form-item>
        <n-form-item label="快速选择">
          <n-space>
            <n-button size="small" @click="setCronPreset('daily')">每天 0 点</n-button>
            <n-button size="small" @click="setCronPreset('daily9am')">每天 9 点</n-button>
            <n-button size="small" @click="setCronPreset('weekly')">每周一 0 点</n-button>
            <n-button size="small" @click="setCronPreset('hourly')">每小时</n-button>
          </n-space>
        </n-form-item>
      </template>

      <!-- Date 触发器 -->
      <template v-if="formData.trigger_type === 'date'">
        <n-form-item label="执行时间" path="trigger_config.run_date">
          <n-date-picker
            :value="dateConfigTimestamp"
            @update:value="updateDateConfig"
            type="datetime"
            placeholder="选择执行时间"
            style="width: 100%"
          />
        </n-form-item>
      </template>

      <!-- Interval 触发器 -->
      <template v-if="formData.trigger_type === 'interval'">
        <n-form-item label="间隔时间" path="trigger_config">
          <n-flex>
            <n-input-number
              :value="intervalConfig.hours"
              @update:value="updateIntervalHours"
              :min="0"
              style="width: 45%"
            >
              <template #suffix>小时</template>
            </n-input-number>
            <n-input-number
              :value="intervalConfig.minutes"
              @update:value="updateIntervalMinutes"
              :min="0"
              style="width: 45%"
            >
              <template #suffix>分钟</template>
            </n-input-number>
          </n-flex>
        </n-form-item>
      </template>

      <n-tabs v-model:value="activeTab" type="segment" animated>
        <!-- Tab 1: 任务列表 -->
        <n-tab-pane name="task-list" tab="任务列表">
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
        <n-tab-pane name="task-settings" tab="任务设置">
          <div v-if="currentSettingTaskName" class="text-center">
            <n-tag type="info" size="large"> 当前设置: {{ currentSettingTaskName }} </n-tag>
          </div>
          <n-scrollbar trigger="none" class="max-h-65 !rounded-[12px]">
            <div v-if="currentSettingTaskId === null">
              <n-empty description="请先在任务列表中选择任务并点击设置按钮" />
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
              <n-empty v-else description="空空如也" />
            </div>
          </n-scrollbar>
        </n-tab-pane>
      </n-tabs>
    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="handleCancel">取消</n-button>
        <n-button type="primary" @click="handleSave" :loading="loading">保存</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue"
import { useMessage, type FormInst, type FormRules } from "naive-ui"
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

const formRules: FormRules = {
  name: [
    { required: true, message: "请输入任务名称", trigger: "blur" },
    { min: 1, max: 100, message: "任务名称长度为 1-100 个字符", trigger: "blur" },
  ],
  trigger_config: {
    cron: [
      { required: true, message: "请输入 Cron 表达式", trigger: "blur" },
      {
        pattern:
          /^(\*|[0-9\-\*,\/]+)\s+(\*|[0-9\-\*,\/]+)\s+(\*|[0-9\-\*,\/]+)\s+(\*|[0-9\-\*,\/]+)\s+(\*|[0-9\-\*,\/]+)$/,
        message: "Cron 表达式格式不正确",
        trigger: "blur",
      },
    ],
  },
  task_list: [
    {
      type: "array",
      required: true,
      min: 1,
      message: "请至少选择一个任务",
      trigger: "change",
    },
  ],
}

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
      message.success(isEditMode.value ? "任务已更新" : "任务已创建")
      showDialog.value = false
      emit("saved")
      resetForm()
    } else {
      message.error(schedulerStore.error || "保存失败")
    }
  } catch (e) {
    message.error("保存失败，请稍后重试")
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
