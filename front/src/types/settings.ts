// 更新设置
export interface UpdateSettings {
  autoUpdate: boolean
  updateChannel: 'stable' | 'beta' | 'dev'
  proxy: string
}

// 外部通知设置
export interface NotificationSettings {
  enabled: boolean
  webhook: string
  notifyOnComplete: boolean
  notifyOnError: boolean
}

// 界面设置
export interface UISettings {
  darkMode: boolean | 'auto'
  language: string
  fontSize: number
}

// 运行设置
export interface RuntimeSettings {
  timeout: number
  reminderInterval: number
  autoRetry: boolean
  maxRetryCount: number
}

// 关于我们（包含联系方式）
export interface AboutInfo {
  version: string
  author: string
  github: string
  license: string
  description: string
  contact: string
  issueUrl: string
}

// 完整设置模型
export interface SettingsModel {
  update: UpdateSettings
  notification: NotificationSettings
  ui: UISettings
  runtime: RuntimeSettings
  about: AboutInfo
}

// 设置更新请求（部分更新）
export type SettingsUpdateRequest = Partial<{
  update: Partial<UpdateSettings>
  notification: Partial<NotificationSettings>
  ui: Partial<UISettings>
  runtime: Partial<RuntimeSettings>
}>
