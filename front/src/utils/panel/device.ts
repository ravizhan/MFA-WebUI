import type {
  AdbDevice,
  ConnectableDevice,
  DeviceControllerCapability,
  GamepadDevice,
  Win32Device,
} from "@/services/api"
import type { PanelLastConnectedDevice } from "@/types/settingsModel"

export function isAdbDevice(value: unknown): value is AdbDevice {
  return !!value && typeof value === "object" && "type" in value && value.type === "Adb"
}

export function isWin32Device(value: unknown): value is Win32Device {
  return !!value && typeof value === "object" && "type" in value && value.type === "Win32"
}

export function isGamepadDevice(value: unknown): value is GamepadDevice {
  return !!value && typeof value === "object" && "type" in value && value.type === "Gamepad"
}

export function buildDeviceLabel(deviceInfo: ConnectableDevice): string {
  if (isAdbDevice(deviceInfo)) {
    return `${deviceInfo.name} (${deviceInfo.address})`
  }
  if (isWin32Device(deviceInfo) || isGamepadDevice(deviceInfo)) {
    return `${deviceInfo.window_name} (${deviceInfo.class_name})`
  }
  return deviceInfo.address
}

export function buildDeviceFingerprint(deviceInfo: ConnectableDevice): string {
  if (isAdbDevice(deviceInfo)) {
    return `adb|${deviceInfo.adb_path}|${deviceInfo.address}`
  }
  if (isWin32Device(deviceInfo)) {
    return `win32|${deviceInfo.hWnd}`
  }
  if (isGamepadDevice(deviceInfo)) {
    return `gamepad|${deviceInfo.hWnd}|${deviceInfo.gamepad_type}`
  }
  return `playcover|${deviceInfo.address}|${deviceInfo.uuid || ""}`
}

export function getPlayCoverDefaultAddress(capabilities: DeviceControllerCapability[]): string {
  const playCoverCapability = capabilities.find((item) => item.type === "PlayCover")
  return playCoverCapability?.default_address || "127.0.0.1:1717"
}

export function getStoredDeviceFingerprint(stored: PanelLastConnectedDevice): string {
  if (stored.fingerprint) {
    return stored.fingerprint
  }
  const normalizedType = stored.type.toLowerCase()
  if (normalizedType === "adb") {
    return `adb|${stored.adb_path}|${stored.address}`
  }
  if (normalizedType === "win32") {
    return `win32|${stored.hWnd}`
  }
  if (normalizedType === "gamepad") {
    return `gamepad|${stored.hWnd}|${stored.gamepad_type}`
  }
  return `playcover|${stored.address}|${stored.uuid}`
}
