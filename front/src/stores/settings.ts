import { defineStore } from 'pinia'
import { getSettings, updateSettings } from '../script/api'
import type { SettingsModel, SettingsUpdateRequest } from '../types/settings'

// 默认设置
const defaultSettings: SettingsModel = {
  update: {
    autoUpdate: true,
    updateChannel: 'stable',
    proxy: '',
  },
  notification: {
    enabled: false,
    webhook: '',
    notifyOnComplete: true,
    notifyOnError: true,
  },
  ui: {
    darkMode: 'auto',
    language: 'zh-CN',
    fontSize: 14,
  },
  runtime: {
    timeout: 300,
    reminderInterval: 30,
    autoRetry: true,
    maxRetryCount: 3,
  },
  about: {
    version: '',
    author: '',
    github: '',
    license: '',
    description: '',
    contact: '',
    issueUrl: '',
  },
}

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    settings: { ...defaultSettings } as SettingsModel,
    loading: false,
    initialized: false,
  }),

  getters: {
    isDarkMode: (state) => {
      if (state.settings.ui.darkMode === 'auto') {
        return window.matchMedia('(prefers-color-scheme: dark)').matches
      }
      return state.settings.ui.darkMode
    },
  },

  actions: {
    // 获取所有设置
    async fetchSettings() {
      this.loading = true
      try {
        const data = await getSettings()
        this.settings = { ...defaultSettings, ...data }
        this.initialized = true
      } catch (error) {
        console.error('Failed to fetch settings:', error)
        // 使用默认设置
        this.settings = { ...defaultSettings }
      } finally {
        this.loading = false
      }
    },

    // 更新设置（支持部分更新）
    async saveSettings(updates: SettingsUpdateRequest) {
      this.loading = true
      try {
        await updateSettings(updates)
        // 合并更新到本地状态
        if (updates.update) {
          this.settings.update = { ...this.settings.update, ...updates.update }
        }
        if (updates.notification) {
          this.settings.notification = { ...this.settings.notification, ...updates.notification }
        }
        if (updates.ui) {
          this.settings.ui = { ...this.settings.ui, ...updates.ui }
        }
        if (updates.runtime) {
          this.settings.runtime = { ...this.settings.runtime, ...updates.runtime }
        }
        return true
      } catch (error) {
        console.error('Failed to save settings:', error)
        return false
      } finally {
        this.loading = false
      }
    },

    // 更新单个设置项的便捷方法
    async updateSingleSetting<K extends keyof SettingsUpdateRequest>(
      category: K,
      key: string,
      value: unknown
    ) {
      const updates = {
        [category]: {
          [key]: value,
        },
      } as SettingsUpdateRequest
      return this.saveSettings(updates)
    },

    // 重置为默认设置
    async resetSettings() {
      const resetData: SettingsUpdateRequest = {
        update: defaultSettings.update,
        notification: defaultSettings.notification,
        ui: defaultSettings.ui,
        runtime: defaultSettings.runtime,
      }
      return this.saveSettings(resetData)
    },
  },
})
