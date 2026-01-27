<template>
  <n-message-provider>
    <div class="flex p-5 gap-6 h-[80vh] overflow-y-auto max-md:flex-col max-md:p-3">
      <div
        class="sticky top-5 w-45 shrink-0 h-fit max-md:relative max-md:top-0 max-md:w-full max-md:mb-4"
      >
        <n-anchor
          :show-rail="true"
          :show-background="true"
          :bound="80"
          type="block"
          offset-target="#setting-content"
        >
          <n-anchor-link title="更新设置" href="#update-settings">
            <template #icon>
              <n-icon><div class="i-mdi-update" /></n-icon>
            </template>
          </n-anchor-link>
          <n-anchor-link title="运行设置" href="#runtime-settings">
            <template #icon>
              <n-icon><div class="i-mdi-cog-play" /></n-icon>
            </template>
          </n-anchor-link>
          <n-anchor-link title="定时任务" href="#scheduler-settings">
            <template #icon>
              <n-icon><div class="i-mdi-clock-outline" /></n-icon>
            </template>
          </n-anchor-link>
          <n-anchor-link title="界面设置" href="#ui-settings">
            <template #icon>
              <n-icon><div class="i-mdi-palette" /></n-icon>
            </template>
          </n-anchor-link>
          <n-anchor-link title="通知设置" href="#notification-settings">
            <template #icon>
              <n-icon><div class="i-mdi-bell" /></n-icon>
            </template>
          </n-anchor-link>
          <n-anchor-link title="关于我们" href="#about">
            <template #icon>
              <n-icon><div class="i-mdi-information" /></n-icon>
            </template>
          </n-anchor-link>
        </n-anchor>
      </div>
      <div id="setting-content" class="flex-1 overflow-y-auto max-md:max-w-full">
        <n-scrollbar>
          <!-- 更新设置 -->
          <n-card id="update-settings" class="mb-6 scroll-mt-5 last:mb-0" title="更新设置">
            <template #header-extra>
              <n-button
                size="small"
                type="primary"
                @click="checkForUpdate"
                :loading="checkingUpdate"
              >
                检查更新
              </n-button>
            </template>
            <n-form label-placement="left" label-width="120">
              <n-form-item label="自动更新">
                <n-switch
                  v-model:value="settings.update.autoUpdate"
                  @update:value="(val: boolean) => handleSettingChange('update', 'autoUpdate', val)"
                />
              </n-form-item>
              <n-form-item label="更新渠道">
                <n-select
                  v-model:value="settings.update.updateChannel"
                  :options="updateChannelOptions"
                  @update:value="
                    (val: string) =>
                      handleSettingChange(
                        'update',
                        'updateChannel',
                        val as SettingsModel['update']['updateChannel'],
                      )
                  "
                />
              </n-form-item>
              <n-form-item label="代理地址">
                <n-input
                  v-model:value="settings.update.proxy"
                  placeholder="http://127.0.0.1:7890"
                  clearable
                  @blur="handleSettingChange('update', 'proxy', settings.update.proxy)"
                />
              </n-form-item>
            </n-form>
          </n-card>

          <!-- 运行设置 -->
          <n-card id="runtime-settings" class="mb-6 scroll-mt-5 last:mb-0" title="运行设置">
            <n-form label-placement="left" label-width="120">
              <n-form-item label="超时时间">
                <n-input-number
                  v-model:value="settings.runtime.timeout"
                  :min="60"
                  :max="3600"
                  :step="30"
                  @update:value="
                    (val: number | null) => handleSettingChange('runtime', 'timeout', val)
                  "
                >
                  <template #suffix>秒</template>
                </n-input-number>
              </n-form-item>
              <n-form-item label="提醒间隔">
                <n-input-number
                  v-model:value="settings.runtime.reminderInterval"
                  :min="5"
                  :max="120"
                  :step="5"
                  @update:value="
                    (val: number | null) => handleSettingChange('runtime', 'reminderInterval', val)
                  "
                >
                  <template #suffix>分钟</template>
                </n-input-number>
              </n-form-item>
              <n-form-item label="自动重试">
                <n-switch
                  v-model:value="settings.runtime.autoRetry"
                  @update:value="(val: boolean) => handleSettingChange('runtime', 'autoRetry', val)"
                />
              </n-form-item>
              <n-form-item label="最大重试次数" v-if="settings.runtime.autoRetry">
                <n-input-number
                  v-model:value="settings.runtime.maxRetryCount"
                  :min="1"
                  :max="10"
                  @update:value="
                    (val: number | null) => handleSettingChange('runtime', 'maxRetryCount', val)
                  "
                />
              </n-form-item>
            </n-form>
          </n-card>

          <!-- 定时任务设置 -->
          <n-card id="scheduler-settings" class="mb-6 scroll-mt-5 last:mb-0" title="定时任务">
            <template #header-extra>
              <n-button size="small" type="primary" @click="openCreateTaskDialog">
                <template #icon>
                  <n-icon><div class="i-mdi-plus" /></n-icon>
                </template>
                新建任务
              </n-button>
            </template>

            <n-collapse>
              <!-- 任务列表折叠面板 -->
              <n-collapse-item title="任务列表" name="tasks">
                <n-empty v-if="schedulerStore.tasks.length === 0" description="暂无定时任务" />
                <n-list v-else>
                  <n-list-item v-for="task in schedulerStore.tasks" :key="task.id">
                    <template #prefix>
                      <n-switch
                        :value="task.enabled"
                        @update:value="(val: boolean) => handleToggleTask(task.id, val)"
                      />
                    </template>
                    <n-thing :title="task.name" :description="task.description">
                      <template #header-extra>
                        <n-space>
                          <n-button size="tiny" @click="openEditTaskDialog(task)">编辑</n-button>
                          <n-button size="tiny" type="error" @click="handleDeleteTask(task.id)"
                            >删除</n-button
                          >
                        </n-space>
                      </template>
                      <template #description>
                        <n-space vertical size="small">
                          <n-text depth="3"
                            >触发:
                            {{ formatTrigger(task.trigger_type, task.trigger_config) }}</n-text
                          >
                          <n-text depth="3"
                            >下次执行: {{ formatDateTime(task.next_run_time) }}</n-text
                          >
                        </n-space>
                      </template>
                    </n-thing>
                  </n-list-item>
                </n-list>
              </n-collapse-item>

              <!-- 执行历史折叠面板 -->
              <n-collapse-item title="执行历史" name="history">
                <n-empty v-if="schedulerStore.executions.length === 0" description="暂无执行记录" />
                <n-timeline v-else>
                  <n-timeline-item
                    v-for="exec in schedulerStore.executions"
                    :key="exec.id"
                    :type="getStatusType(exec.status)"
                    :title="exec.task_name"
                    :time="formatDateTime(exec.started_at)"
                  >
                    <template #icon>
                      <n-icon>
                        <div :class="getStatusIcon(exec.status)" />
                      </n-icon>
                    </template>
                    <n-text :type="getStatusTextType(exec.status)">
                      {{ getStatusLabel(exec.status) }}
                    </n-text>
                    <n-text v-if="exec.error_message" type="error" depth="3">
                      {{ exec.error_message }}
                    </n-text>
                  </n-timeline-item>
                </n-timeline>
              </n-collapse-item>
            </n-collapse>
          </n-card>

          <!-- 界面设置 -->
          <n-card id="ui-settings" class="mb-6 scroll-mt-5 last:mb-0" title="界面设置">
            <n-form label-placement="left" label-width="120">
              <n-form-item label="深色模式">
                <n-select
                  v-model:value="settings.ui.darkMode"
                  :options="darkModeOptions"
                  @update:value="
                    (val: string | boolean) =>
                      (val === 'auto' || typeof val === 'boolean') &&
                      handleSettingChange('ui', 'darkMode', val as SettingsModel['ui']['darkMode'])
                  "
                />
              </n-form-item>
            </n-form>
          </n-card>

          <!-- 通知设置 -->
          <n-card id="notification-settings" class="mb-6 scroll-mt-5 last:mb-0" title="通知设置">
            <template #header-extra>
              <n-button
                size="small"
                type="info"
                @click="testNotification"
                :disabled="
                  !settings.notification.externalNotification || !settings.notification.webhook
                "
              >
                测试外部通知
              </n-button>
            </template>
            <n-form label-placement="left" label-width="120">
              <n-form-item label="启用通知">
                <n-space>
                  <n-checkbox
                    v-model:checked="settings.notification.systemNotification"
                    @update:checked="
                      (val: boolean) =>
                        handleSettingChange('notification', 'systemNotification', val)
                    "
                  >
                    系统通知
                  </n-checkbox>
                  <n-checkbox
                    v-model:checked="settings.notification.browserNotification"
                    @update:checked="
                      (val: boolean) =>
                        handleSettingChange('notification', 'browserNotification', val)
                    "
                  >
                    浏览器通知
                  </n-checkbox>
                  <n-checkbox
                    v-model:checked="settings.notification.externalNotification"
                    @update:checked="
                      (val: boolean) =>
                        handleSettingChange('notification', 'externalNotification', val)
                    "
                  >
                    外部通知
                  </n-checkbox>
                </n-space>
              </n-form-item>
            </n-form>
            <template v-if="settings.notification.externalNotification">
              <n-form label-placement="top">
                <n-form-item label="url *">
                  <n-input
                    v-model:value="settings.notification.webhook"
                    placeholder="https://..."
                    @blur="
                      handleSettingChange('notification', 'webhook', settings.notification.webhook)
                    "
                  />
                </n-form-item>
                <n-form-item label="content_type" v-if="settings.notification.method !== 'GET'">
                  <n-select
                    v-model:value="settings.notification.contentType"
                    :options="contentTypeOptions"
                    @update:value="
                      (val: string) =>
                        handleSettingChange(
                          'notification',
                          'contentType',
                          val as SettingsModel['notification']['contentType'],
                        )
                    "
                  />
                </n-form-item>
                <n-form-item label="headers">
                  <n-input
                    v-model:value="settings.notification.headers"
                    placeholder="HTTP headers in JSON format"
                    @blur="
                      handleSettingChange('notification', 'headers', settings.notification.headers)
                    "
                  />
                </n-form-item>
                <n-form-item label="body">
                  <n-input
                    v-model:value="settings.notification.body"
                    type="textarea"
                    placeholder='{"desp":"{{message}}","title":"{{title}}"}'
                    :autosize="{ minRows: 2, maxRows: 5 }"
                    @blur="handleSettingChange('notification', 'body', settings.notification.body)"
                  />
                </n-form-item>
                <n-form-item label="username">
                  <n-input
                    v-model:value="settings.notification.username"
                    @blur="
                      handleSettingChange(
                        'notification',
                        'username',
                        settings.notification.username,
                      )
                    "
                  />
                </n-form-item>
                <n-form-item label="password">
                  <n-input
                    v-model:value="settings.notification.password"
                    type="password"
                    show-password-on="click"
                    @blur="
                      handleSettingChange(
                        'notification',
                        'password',
                        settings.notification.password,
                      )
                    "
                  />
                </n-form-item>
                <n-form-item label="method">
                  <n-select
                    v-model:value="settings.notification.method"
                    :options="methodOptions"
                    @update:value="
                      (val: string) =>
                        handleSettingChange(
                          'notification',
                          'method',
                          val as SettingsModel['notification']['method'],
                        )
                    "
                  />
                </n-form-item>
              </n-form>
            </template>
            <n-divider />
            <n-form label-placement="left" label-width="120">
              <n-form-item label="完成时通知">
                <n-switch
                  v-model:value="settings.notification.notifyOnComplete"
                  @update:value="
                    (val: boolean) => handleSettingChange('notification', 'notifyOnComplete', val)
                  "
                />
              </n-form-item>
              <n-form-item label="错误时通知">
                <n-switch
                  v-model:value="settings.notification.notifyOnError"
                  @update:value="
                    (val: boolean) => handleSettingChange('notification', 'notifyOnError', val)
                  "
                />
              </n-form-item>
            </n-form>
          </n-card>

          <!-- 关于我们 -->
          <n-card id="about" class="mb-6 scroll-mt-5 last:mb-0" title="关于我们">
            <n-descriptions bordered :column="1">
              <n-descriptions-item label="版本">
                {{ settings.about.version || "未知" }}
              </n-descriptions-item>
              <n-descriptions-item label="作者">
                {{ settings.about.author || "未知" }}
              </n-descriptions-item>
              <n-descriptions-item label="开源协议">
                {{ settings.about.license || "MIT" }}
              </n-descriptions-item>
              <n-descriptions-item label="项目主页">
                <n-button
                  text
                  tag="a"
                  :href="settings.about.github || 'https://github.com/ravizhan/MWU'"
                  target="_blank"
                  type="primary"
                >
                  <template #icon>
                    <n-icon><div class="i-mdi-github" /></n-icon>
                  </template>
                  {{ settings.about.github || "https://github.com/ravizhan/MWU" }}
                </n-button>
              </n-descriptions-item>
              <n-descriptions-item label="问题反馈">
                <n-button
                  text
                  tag="a"
                  :href="settings.about.issueUrl || 'https://github.com/ravizhan/MWU/issues'"
                  target="_blank"
                  type="primary"
                >
                  <template #icon>
                    <n-icon><div class="i-mdi-bug" /></n-icon>
                  </template>
                  GitHub Issues
                </n-button>
              </n-descriptions-item>
              <n-descriptions-item label="联系方式" v-if="settings.about.contact">
                {{ settings.about.contact }}
              </n-descriptions-item>
              <n-descriptions-item label="项目简介">
                {{ settings.about.description || "基于 Vue 的 MAAFramework 通用 GUI 项目" }}
              </n-descriptions-item>
            </n-descriptions>
            <n-divider />
            <n-space>
              <n-button type="warning" @click="handleResetSettings"> 重置所有设置 </n-button>
            </n-space>
          </n-card>
        </n-scrollbar>
      </div>
    </div>

    <!-- 定时任务弹窗 -->
    <SchedulerTaskDialog
      v-model:show="showTaskDialog"
      :task="editingTask"
      @saved="handleTaskSaved"
    />
  </n-message-provider>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from "vue"
import { useSettingsStore } from "../stores/settings"
import { useSchedulerStore } from "../stores/scheduler"
import { checkUpdate, testNotificationApi } from "../script/api"
import { useMessage, useDialog } from "naive-ui"
import type { SettingsModel } from "../types/settings"
import type { ScheduledTask, TriggerConfig, ExecutionStatus } from "../types/scheduler"
import SchedulerTaskDialog from "../components/SchedulerTaskDialog.vue"

type EditableCategory = Exclude<keyof SettingsModel, "about">
type MaybeNullForNumbers<T> = T extends number ? T | null : T
type EditableSettingValue<
  K extends EditableCategory,
  P extends keyof SettingsModel[K],
> = MaybeNullForNumbers<SettingsModel[K][P]>

const message = useMessage()
const dialog = useDialog()
const settingsStore = useSettingsStore()
const schedulerStore = useSchedulerStore()

if (typeof window !== "undefined") {
  window.$message = message
}

const settings = computed<SettingsModel>(() => settingsStore.settings)

const checkingUpdate = ref(false)
const showTaskDialog = ref(false)
const editingTask = ref<ScheduledTask | null>(null)

const updateChannelOptions = [
  { label: "稳定版", value: "stable" },
  { label: "测试版", value: "beta" },
]

const methodOptions = [
  { label: "POST", value: "POST" },
  { label: "GET", value: "GET" },
]

const contentTypeOptions = [
  { label: "application/json", value: "application/json" },
  { label: "application/x-www-form-urlencoded", value: "application/x-www-form-urlencoded" },
]

const darkModeOptions = [
  { label: "跟随系统", value: "auto" },
  { label: "关", value: false },
  { label: "开", value: true },
]

onMounted(() => {
  if (!settingsStore.initialized) {
    settingsStore.fetchSettings()
  }
  // 加载定时任务数据
  schedulerStore.fetchTasks()
  schedulerStore.fetchExecutions()
})

const handleSettingChange = async <K extends EditableCategory, P extends keyof SettingsModel[K]>(
  category: K,
  key: P,
  value: EditableSettingValue<K, P>,
) => {
  if (value === null) return
  await settingsStore.updateSetting(category, key, value as SettingsModel[K][P])
}

const checkForUpdate = async () => {
  checkingUpdate.value = true
  try {
    const result = await checkUpdate()
    if (result.hasUpdate) {
      dialog.info({
        title: "发现新版本",
        content: `新版本 ${result.version} 已发布！\n\n更新日志：\n${result.changelog || "暂无"}`,
        positiveText: "前往更新",
        negativeText: "稍后",
        onPositiveClick: () => {
          if (result.downloadUrl) {
            window.open(result.downloadUrl, "_blank")
          } else {
            window.open(settings.value.about.github, "_blank")
          }
        },
      })
    } else {
      message.success("当前已是最新版本")
    }
  } catch (error) {
    message.error("检查更新失败")
  } finally {
    checkingUpdate.value = false
  }
}

const testNotification = async () => {
  message.info("正在发送测试通知...")
  try {
    const result = await testNotificationApi()
    if (result.status === "success") {
      message.success("测试通知已发送")
    } else {
      message.error(`发送失败: ${result.message}`)
    }
  } catch (error) {
    message.error("发送测试通知时发生错误")
    console.error(error)
  }
}

const handleResetSettings = () => {
  dialog.warning({
    title: "确认重置",
    content: "确定要将所有设置重置为默认值吗？此操作不可撤销。",
    positiveText: "确定重置",
    negativeText: "取消",
    onPositiveClick: async () => {
      const success = await settingsStore.resetSettings()
      if (success) {
        message.success("设置已重置为默认值")
      }
    },
  })
}

// ==================== 定时任务相关 ====================

function openCreateTaskDialog() {
  editingTask.value = null
  showTaskDialog.value = true
}

function openEditTaskDialog(task: ScheduledTask) {
  editingTask.value = task
  showTaskDialog.value = true
}

async function handleToggleTask(taskId: string, enabled: boolean) {
  await schedulerStore.toggleTask(taskId, enabled)
  if (schedulerStore.error) {
    message.error(schedulerStore.error)
  }
}

async function handleDeleteTask(taskId: string) {
  dialog.warning({
    title: "确认删除",
    content: "确定要删除这个定时任务吗？",
    positiveText: "确定删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      const success = await schedulerStore.deleteTask(taskId)
      if (success) {
        message.success("任务已删除")
      } else {
        message.error(schedulerStore.error || "删除失败")
      }
    },
  })
}

function handleTaskSaved() {
  schedulerStore.fetchTasks()
  schedulerStore.fetchExecutions()
}

function formatTrigger(triggerType: string, triggerConfig: TriggerConfig): string {
  switch (triggerType) {
    case "cron":
      return `Cron ${(triggerConfig as any).cron}`
    case "date":
      return `指定时间 ${formatDateTime((triggerConfig as any).run_date)}`
    case "interval":
      const config = triggerConfig as any
      const parts: string[] = []
      if (config.hours) parts.push(`${config.hours}小时`)
      if (config.minutes) parts.push(`${config.minutes}分钟`)
      return `间隔 ${parts.join(" ")}`
    default:
      return "未知"
  }
}

function formatDateTime(dateStr?: string): string {
  if (!dateStr) return "未设置"
  const date = new Date(dateStr)
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function getStatusType(
  status: ExecutionStatus,
): "success" | "error" | "warning" | "info" | "default" {
  switch (status) {
    case "success":
      return "success"
    case "failed":
      return "error"
    case "running":
      return "info"
    case "stopped":
      return "warning"
    default:
      return "default"
  }
}

function getStatusIcon(status: ExecutionStatus): string {
  switch (status) {
    case "success":
      return "i-mdi-check-circle"
    case "failed":
      return "i-mdi-close-circle"
    case "running":
      return "i-mdi-loading"
    case "stopped":
      return "i-mdi-pause-circle"
    default:
      return "i-mdi-help-circle"
  }
}

function getStatusTextType(
  status: ExecutionStatus,
): "success" | "error" | "warning" | "info" | "default" {
  switch (status) {
    case "success":
      return "success"
    case "failed":
      return "error"
    case "running":
      return "info"
    case "stopped":
      return "warning"
    default:
      return "default"
  }
}

function getStatusLabel(status: ExecutionStatus): string {
  switch (status) {
    case "success":
      return "成功"
    case "failed":
      return "失败"
    case "running":
      return "运行中"
    case "stopped":
      return "已停止"
    default:
      return "未知"
  }
}
</script>
<style scoped>
.n-anchor-link {
  line-height: 2;
}
</style>
