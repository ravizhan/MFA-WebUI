<template>
  <n-message-provider>
    <div
      class="flex p-5 gap-6 min-h-[60vh] max-h-[65.5vh] overflow-y-auto max-md:flex-col max-md:p-3"
    >
      <!-- 左侧锚点导航 -->
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
          <n-anchor-link title="界面设置" href="#ui-settings">
            <template #icon>
              <n-icon><div class="i-mdi-palette" /></n-icon>
            </template>
          </n-anchor-link>
          <n-anchor-link title="外部通知" href="#notification-settings">
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

      <!-- 右侧设置内容 -->
      <div id="setting-content" class="flex-1 max-w-200 overflow-y-auto max-md:max-w-full">
        <n-spin :show="settingsStore.loading">
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

          <!-- 外部通知 -->
          <n-card id="notification-settings" class="mb-6 scroll-mt-5 last:mb-0" title="外部通知">
            <template #header-extra>
              <n-button
                size="small"
                type="info"
                @click="testNotification"
                :disabled="!settings.notification.enabled || !settings.notification.webhook"
              >
                测试通知
              </n-button>
            </template>
            <n-form label-placement="left" label-width="120">
              <n-form-item label="启用通知">
                <n-switch
                  v-model:value="settings.notification.enabled"
                  @update:value="
                    (val: boolean) => handleSettingChange('notification', 'enabled', val)
                  "
                />
              </n-form-item>
              <template v-if="settings.notification.enabled">
                <n-form-item label="Webhook 地址">
                  <n-input
                    v-model:value="settings.notification.webhook"
                    placeholder="https://your-webhook-url.com"
                    type="textarea"
                    :autosize="{ minRows: 2, maxRows: 4 }"
                    @blur="
                      handleSettingChange('notification', 'webhook', settings.notification.webhook)
                    "
                  />
                </n-form-item>
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
              </template>
            </n-form>
          </n-card>

          <!-- 关于我们 -->
          <n-card id="about" class="mb-6 scroll-mt-5 last:mb-0" title="关于我们">
            <n-descriptions bordered :column="1">
              <n-descriptions-item label="版本">
                {{ settings.about.version || '未知' }}
              </n-descriptions-item>
              <n-descriptions-item label="作者">
                {{ settings.about.author || '未知' }}
              </n-descriptions-item>
              <n-descriptions-item label="开源协议">
                {{ settings.about.license || 'MIT' }}
              </n-descriptions-item>
              <n-descriptions-item label="项目主页">
                <n-button
                  text
                  tag="a"
                  :href="settings.about.github || 'https://github.com/ravizhan/MFA-WebUI'"
                  target="_blank"
                  type="primary"
                >
                  <template #icon>
                    <n-icon><div class="i-mdi-github" /></n-icon>
                  </template>
                  {{ settings.about.github || 'https://github.com/ravizhan/MFA-WebUI' }}
                </n-button>
              </n-descriptions-item>
              <n-descriptions-item label="问题反馈">
                <n-button
                  text
                  tag="a"
                  :href="settings.about.issueUrl || 'https://github.com/ravizhan/MFA-WebUI/issues'"
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
                {{ settings.about.description || '基于 MAA 框架的 Web UI 界面' }}
              </n-descriptions-item>
            </n-descriptions>
            <n-divider />
            <n-space>
              <n-button type="warning" @click="handleResetSettings"> 重置所有设置 </n-button>
            </n-space>
          </n-card>
        </n-spin>
      </div>
    </div>
  </n-message-provider>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { checkUpdate } from '../script/api'
import { useMessage, useDialog } from 'naive-ui'
import type { SettingsModel } from '../types/settings'

type EditableCategory = Exclude<keyof SettingsModel, 'about'>
type MaybeNullForNumbers<T> = T extends number ? T | null : T
type EditableSettingValue<
  K extends EditableCategory,
  P extends keyof SettingsModel[K],
> = MaybeNullForNumbers<SettingsModel[K][P]>

const message = useMessage()
const dialog = useDialog()
const settingsStore = useSettingsStore()

if (typeof window !== 'undefined') {
  window.$message = message
}

const settings = computed<SettingsModel>(() => settingsStore.settings)

const checkingUpdate = ref(false)

const updateChannelOptions = [
  { label: '稳定版', value: 'stable' },
  { label: '测试版', value: 'beta' },
]

const darkModeOptions = [
  { label: '跟随系统', value: 'auto' },
  { label: '关', value: false },
  { label: '开', value: true },
]

onMounted(() => {
  if (!settingsStore.initialized) {
    settingsStore.fetchSettings()
  }
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
        title: '发现新版本',
        content: `新版本 ${result.version} 已发布！\n\n更新日志：\n${result.changelog || '暂无'}`,
        positiveText: '前往更新',
        negativeText: '稍后',
        onPositiveClick: () => {
          window.open(settings.value.about.github, '_blank')
        },
      })
    } else {
      message.success('当前已是最新版本')
    }
  } catch (error) {
    message.error('检查更新失败')
  } finally {
    checkingUpdate.value = false
  }
}

const testNotification = () => {
  message.info('正在发送测试通知...')
  // TODO: 调用后端测试通知接口
}

const handleResetSettings = () => {
  dialog.warning({
    title: '确认重置',
    content: '确定要将所有设置重置为默认值吗？此操作不可撤销。',
    positiveText: '确定重置',
    negativeText: '取消',
    onPositiveClick: async () => {
      const success = await settingsStore.resetSettings()
      if (success) {
        message.success('设置已重置为默认值')
      }
    },
  })
}
</script>
