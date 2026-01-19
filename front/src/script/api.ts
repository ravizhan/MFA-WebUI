import type { InterfaceModel } from "../types/interfaceV2"

interface ApiResponse {
  status: string
  message: string
}

export interface Device {
  name: string
  adb_path: string
  address: string
  screencap_methods: string
  input_methods: string
  config: object
}

interface DeviceResponse {
  status: string
  devices: Device[]
}

interface ResourceResponse {
  status: string
  resource: string[]
}

export function startTask(task_list: string[], options: Record<string, string>): void {
  fetch("/api/start", {
    method: "POST",
    body: JSON.stringify({ tasks: task_list, options: options }),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        // @ts-ignore
        window.$message.success("任务开始")
      } else {
        // @ts-ignore
        window.$message.error(data.message)
      }
    })
}

export function stopTask(): void {
  fetch("/api/stop", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        // @ts-ignore
        window.$message.success("正在中止任务，请稍后")
      } else {
        // @ts-ignore
        window.$message.error(data.message)
      }
    })
}

export function getDevices(): Promise<Device[]> {
  return fetch("/api/device", { method: "GET" })
    .then((res) => res.json())
    .then((data: DeviceResponse) => data.devices)
}

export function postDevices(device: Device): void {
  fetch("/api/device", {
    method: "POST",
    body: JSON.stringify(device),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        // @ts-ignore
        window.$message.success("设备连接成功")
      } else {
        // @ts-ignore
        window.$message.error("设备连接成功，请检查终端日志")
      }
    })
}

export function getInterface(): Promise<InterfaceModel> {
  return fetch("/api/interface", { method: "GET" }).then((res) => res.json())
}

export function getResource(): Promise<string[]> {
  return fetch("/api/resource", { method: "GET" })
    .then((res) => res.json())
    .then((data: ResourceResponse) => data.resource)
}

export function postResource(name: string): void {
  fetch("/api/resource?name=" + name, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        // @ts-ignore
        window.$message.success("资源添加成功")
      } else {
        // @ts-ignore
        window.$message.error(data.message)
      }
    })
}

// ==================== 设置相关 API ====================

import type { SettingsModel } from "../types/settings"

interface SettingsResponse {
  status: string
  data: SettingsModel
}

export function getSettings(): Promise<SettingsModel> {
  return fetch("/api/settings", { method: "GET" })
    .then((res) => res.json())
    .then((data: SettingsResponse) => data.data)
}

export function updateSettings(settings: SettingsModel): Promise<boolean> {
  return fetch("/api/settings", {
    method: "POST",
    body: JSON.stringify(settings),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        // @ts-ignore
        window.$message.success("设置已保存")
        return true
      } else {
        // @ts-ignore
        window.$message.error(data.message || "保存失败")
        return false
      }
    })
    .catch((error) => {
      console.error("Failed to update settings:", error)
      // @ts-ignore
      window.$message.error("网络错误，请稍后重试")
      return false
    })
}

// 检查更新
export function checkUpdate(): Promise<{
  hasUpdate: boolean
  version?: string
  changelog?: string
}> {
  return fetch("/api/update/check", { method: "GET" })
    .then((res) => res.json())
    .then((data) => ({
      hasUpdate: data.has_update || false,
      version: data.version,
      changelog: data.changelog,
    }))
    .catch((error) => {
      console.error("Failed to check update:", error)
      return { hasUpdate: false }
    })
}


// ==================== 用户配置相关 API ====================

export interface UserConfig {
  taskOrder?: string[]
  taskChecked?: Record<string, boolean>
  taskOptions?: Record<string, string>
}

interface UserConfigResponse {
  status: string
  config: UserConfig
  message?: string
}

export function getUserConfig(): Promise<UserConfig> {
  return fetch("/api/user-config", { method: "GET" })
    .then((res) => res.json())
    .then((data: UserConfigResponse) => {
      if (data.status === "success") {
        return data.config || {}
      } else {
        console.error("Failed to load user config:", data.message)
        return {}
      }
    })
    .catch((error) => {
      console.error("Failed to load user config:", error)
      return {}
    })
}

export function saveUserConfig(config: UserConfig): Promise<boolean> {
  return fetch("/api/user-config", {
    method: "POST",
    body: JSON.stringify(config),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        return true
      } else {
        console.error("Failed to save user config:", data.message)
        return false
      }
    })
    .catch((error) => {
      console.error("Failed to save user config:", error)
      return false
    })
}

export function resetUserConfig(): Promise<boolean> {
  return fetch("/api/user-config", {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        return true
      } else {
        console.error("Failed to reset user config:", data.message)
        return false
      }
    })
    .catch((error) => {
      console.error("Failed to reset user config:", error)
      return false
    })
}
