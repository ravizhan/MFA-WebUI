import { showGlobalMessage } from "../message"
import type { ApiResponse } from "./shared"

export type DeviceControllerType = "Adb" | "Win32" | "Gamepad" | "PlayCover"

export interface AdbDevice {
  type: "Adb"
  name: string
  adb_path: string
  address: string
  screencap_methods: string
  input_methods: string
  config: Record<string, unknown>
}

export interface Win32Device {
  type: "Win32"
  hWnd: number
  class_name: string
  window_name: string
  screencap_methods: number
  input_methods: number
}

export interface GamepadDevice {
  type: "Gamepad"
  hWnd: number
  class_name: string
  window_name: string
  screencap_methods: number
  gamepad_type: number
}

export interface PlayCoverDevice {
  type: "PlayCover"
  name?: string
  address: string
  uuid?: string
}

export type ConnectableDevice = AdbDevice | Win32Device | GamepadDevice | PlayCoverDevice

export interface ConnectDevicePayload {
  controller_name: string
  device: ConnectableDevice
}

export interface DeviceControllerCapability {
  name: string
  type: DeviceControllerType
  label: string
  display_label: string
  enabled: boolean
  reason: string
  search_mode: "select" | "input"
  default_address: string
}

export interface DeviceSearchData {
  controllers: DeviceControllerCapability[]
  selected_controller: string | null
  devices: ConnectableDevice[]
}

interface DeviceResponse {
  status: string
  data: DeviceSearchData
}

export function getDevices(controllerName?: string): Promise<DeviceSearchData> {
  const query = controllerName ? `?controller=${encodeURIComponent(controllerName)}` : ""
  return fetch(`/api/device${query}`, { method: "GET" })
    .then((res) => res.json())
    .then((data: DeviceResponse) => data.data)
}

export function postDevices(payload: ConnectDevicePayload): Promise<boolean> {
  return fetch("/api/device", {
    method: "POST",
    body: JSON.stringify({
      ...payload.device,
      controller_name: payload.controller_name,
    }),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        showGlobalMessage("success", "设备连接成功")
        return true
      }
      showGlobalMessage("error", "设备连接失败，请检查终端日志")
      return false
    })
}
