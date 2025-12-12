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
    systemPrefersDark: false,
    systemThemeListenerReady: false,
  }),

  getters: {
    isDarkMode(): boolean {
      if (this.settings.ui.darkMode === 'auto') {
        return this.systemPrefersDark
      }
      return Boolean(this.settings.ui.darkMode)
    },
  },

  actions: {
    ensureSystemThemeListener() {
      if (this.systemThemeListenerReady) return
      if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
        this.systemThemeListenerReady = true
        this.systemPrefersDark = false
        return
      }

      const media = window.matchMedia('(prefers-color-scheme: dark)')
      this.systemPrefersDark = media.matches

      const onChange = (e: MediaQueryListEvent) => {
        this.systemPrefersDark = e.matches
      }

      if (typeof media.addEventListener === 'function') {
        media.addEventListener('change', onChange)
      } else if (
        typeof (media as unknown as { addListener?: (cb: (e: MediaQueryListEvent) => void) => void })
          .addListener === 'function'
      ) {
        ;(
          media as unknown as {
            addListener: (cb: (e: MediaQueryListEvent) => void) => void
          }
        ).addListener(onChange)
      }

      this.systemThemeListenerReady = true
    },

    async fetchSettings() {
      this.loading = true
      try {
        this.ensureSystemThemeListener()
        const data = await getSettings()
        this.settings = {
          update: { ...defaultSettings.update, ...data?.update },
          notification: { ...defaultSettings.notification, ...data?.notification },
          ui: { ...defaultSettings.ui, ...data?.ui },
          runtime: { ...defaultSettings.runtime, ...data?.runtime },
          about: { ...defaultSettings.about, ...data?.about },
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
      value: SettingsModel[K][P],
    ) {
      if (category === 'ui' && key === 'darkMode' && value === 'auto') {
        this.ensureSystemThemeListener()
      }
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
