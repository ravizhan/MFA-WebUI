import { defineStore } from 'pinia'
import { getSettings, updateSettings } from '../script/api'
import type { SettingsModel } from '../types/settings'

const defaultSettings: SettingsModel = {
  update: {
    autoUpdate: true,
    updateChannel: 'stable',
    proxy: '',
  },
  notification: {
    enabled: true,
    webhook: '',
    notifyOnComplete: true,
    notifyOnError: true,
  },
  ui: {
    darkMode: 'auto',
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
    async fetchSettings() {
      this.loading = true
      try {
        const data = await getSettings()
        this.settings = {
          update: { ...defaultSettings.update, ...(data?.update || {}) },
          notification: { ...defaultSettings.notification, ...(data?.notification || {}) },
          ui: { ...defaultSettings.ui, ...(data?.ui || {}) },
          runtime: { ...defaultSettings.runtime, ...(data?.runtime || {}) },
          about: { ...defaultSettings.about, ...(data?.about || {}) },
        }
        this.initialized = true
      } catch (error) {
        console.error('Failed to fetch settings:', error)
        this.settings = { ...defaultSettings }
      } finally {
        this.loading = false
      }
    },

    async saveSettings(newSettings?: SettingsModel) {
      this.loading = true
      try {
        const payload = newSettings || this.settings
        const success = await updateSettings(payload)
        if (success) {
          this.settings = { ...payload }
        }
        return success
      } catch (error) {
        console.error('Failed to save settings:', error)
        return false
      } finally {
        this.loading = false
      }
    },

    // 更新单个设置项的便捷方法
    async updateSetting<K extends keyof SettingsModel, P extends keyof SettingsModel[K]>(
      category: K,
      key: P,
      value: SettingsModel[K][P]
    ) {
      const updatedSettings: SettingsModel = {
        ...this.settings,
        [category]: {
          ...this.settings[category],
          [key]: value,
        },
      }
      this.settings = updatedSettings
      return this.saveSettings(updatedSettings)
    },

    async resetSettings() {
      const resetData: SettingsModel = {
        update: { ...defaultSettings.update },
        notification: { ...defaultSettings.notification },
        ui: { ...defaultSettings.ui },
        runtime: { ...defaultSettings.runtime },
        about: { ...this.settings.about },
      }
      this.settings = resetData
      return this.saveSettings(resetData)
    },
  },
})
