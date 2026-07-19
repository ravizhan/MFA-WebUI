import { describe, expect, it } from "vitest"
import {
  isAdbDevice,
  isWin32Device,
  isGamepadDevice,
  buildDeviceLabel,
  buildDeviceFingerprint,
  findDeviceByIdentityOrFingerprint,
  getDeviceIdentity,
  getPlayCoverDefaultAddress,
  getStoredDeviceFingerprint,
  getStoredDeviceIdentity,
  storedDeviceMatchesController,
} from "@/utils/panel/device"
import type { AdbDevice, GamepadDevice, PlayCoverDevice, Win32Device } from "@/services/api"
import type { PanelLastConnectedDevice } from "@/types/settingsModel"

const adbDevice: AdbDevice = {
  type: "Adb",
  name: "adb-device",
  adb_path: "/usr/bin/adb",
  address: "127.0.0.1:5555",
  screencap_methods: 0,
  input_methods: 0,
  config: {},
}

const win32Device: Win32Device = {
  type: "Win32",
  hWnd: 12345,
  class_name: "class-win32",
  window_name: "window-win32",
  screencap_methods: 0,
  input_methods: 0,
}

const gamepadDevice: GamepadDevice = {
  type: "Gamepad",
  hWnd: 67890,
  class_name: "class-gamepad",
  window_name: "window-gamepad",
  screencap_methods: 0,
  gamepad_type: 1,
}

const playCoverDevice: PlayCoverDevice = {
  type: "PlayCover",
  name: "playcover-device",
  address: "127.0.0.1:1717",
  uuid: "uuid-001",
}

describe("device type guards", () => {
  it("narrows by type and rejects null/non-objects", () => {
    expect(isAdbDevice(adbDevice)).toBe(true)
    expect(isAdbDevice(win32Device)).toBe(false)
    expect(isAdbDevice(null)).toBe(false)

    expect(isWin32Device(win32Device)).toBe(true)
    expect(isWin32Device(adbDevice)).toBe(false)
    expect(isWin32Device(12345)).toBe(false)

    expect(isGamepadDevice(gamepadDevice)).toBe(true)
    expect(isGamepadDevice(win32Device)).toBe(false)
    expect(isGamepadDevice(true)).toBe(false)
  })
})

describe("getDeviceIdentity / getStoredDeviceIdentity", () => {
  it("returns type-specific identity for live and stored devices", () => {
    expect(getDeviceIdentity(adbDevice)).toBe("127.0.0.1:5555")
    expect(getDeviceIdentity(win32Device)).toBe("12345")
    expect(getDeviceIdentity(gamepadDevice)).toBe("67890|1")
    expect(getDeviceIdentity(playCoverDevice)).toBe("127.0.0.1:1717")

    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const storedAdb = { type: "Adb", address: "127.0.0.1:5555" } as PanelLastConnectedDevice
    expect(getStoredDeviceIdentity(storedAdb)).toBe("127.0.0.1:5555")

    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const storedWin32 = { type: "Win32", hWnd: 12345 } as PanelLastConnectedDevice
    expect(getStoredDeviceIdentity(storedWin32)).toBe("12345")

    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const storedGamepad = {
      type: "Gamepad",
      hWnd: 67890,
      gamepad_type: 1,
    } as PanelLastConnectedDevice
    expect(getStoredDeviceIdentity(storedGamepad)).toBe("67890|1")

    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const storedPlayCover = {
      type: "PlayCover",
      address: "127.0.0.1:1717",
    } as PanelLastConnectedDevice
    expect(getStoredDeviceIdentity(storedPlayCover)).toBe("127.0.0.1:1717")
  })
})

describe("storedDeviceMatchesController", () => {
  it("matches by controller_name or falls back to type", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const byName = { type: "Adb", controller_name: "adb" } as PanelLastConnectedDevice
    expect(storedDeviceMatchesController(byName, { name: "adb", type: "Adb" })).toBe(true)
    expect(storedDeviceMatchesController(byName, { name: "other", type: "Adb" })).toBe(false)

    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const byType = { type: "Win32", controller_name: "" } as PanelLastConnectedDevice
    expect(storedDeviceMatchesController(byType, { name: "win32", type: "Win32" })).toBe(true)
    expect(storedDeviceMatchesController(byType, { name: "adb", type: "Adb" })).toBe(false)
  })
})

describe("findDeviceByIdentityOrFingerprint", () => {
  it("prefers identity match and returns undefined when neither matches", () => {
    const custom: AdbDevice = { ...adbDevice, name: "", adb_path: "" }
    const scanned: AdbDevice = { ...adbDevice, name: "phone", adb_path: "/usr/bin/adb" }
    expect(findDeviceByIdentityOrFingerprint([scanned], custom)).toEqual(scanned)

    const other: AdbDevice = { ...adbDevice, address: "10.0.0.1:5555", adb_path: "/other/adb" }
    expect(findDeviceByIdentityOrFingerprint([other], adbDevice)).toBeUndefined()
    expect(findDeviceByIdentityOrFingerprint([adbDevice], adbDevice)).toEqual(adbDevice)
  })
})

describe("buildDeviceLabel", () => {
  it("builds labels per device type with empty-name fallbacks", () => {
    expect(buildDeviceLabel(adbDevice)).toBe("adb-device(127.0.0.1:5555)")
    expect(buildDeviceLabel({ ...adbDevice, name: "" })).toBe("127.0.0.1:5555")
    expect(buildDeviceLabel({ ...adbDevice, name: "   " })).toBe("127.0.0.1:5555")
    expect(buildDeviceLabel(win32Device)).toBe("window-win32(class-win32)")
    expect(buildDeviceLabel({ ...win32Device, window_name: "" })).toBe("class-win32")
    expect(buildDeviceLabel(gamepadDevice)).toBe("window-gamepad(class-gamepad)")
    expect(buildDeviceLabel(playCoverDevice)).toBe("playcover-device(127.0.0.1:1717)")
    expect(buildDeviceLabel({ type: "PlayCover", address: "127.0.0.1:1717" })).toBe(
      "127.0.0.1:1717",
    )
  })
})

describe("buildDeviceFingerprint / getStoredDeviceFingerprint", () => {
  it("builds type-specific fingerprints for live and stored devices", () => {
    expect(buildDeviceFingerprint(adbDevice)).toBe("adb|/usr/bin/adb|127.0.0.1:5555")
    expect(buildDeviceFingerprint(win32Device)).toBe("win32|12345")
    expect(buildDeviceFingerprint(gamepadDevice)).toBe("gamepad|67890|1")
    expect(buildDeviceFingerprint(playCoverDevice)).toBe("playcover|127.0.0.1:1717|uuid-001")
    expect(buildDeviceFingerprint({ type: "PlayCover", address: "127.0.0.1:1717" })).toBe(
      "playcover|127.0.0.1:1717|",
    )

    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const withFingerprint = { fingerprint: "fp-001" } as PanelLastConnectedDevice
    expect(getStoredDeviceFingerprint(withFingerprint)).toBe("fp-001")

    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const storedAdbFp = {
      type: "Adb",
      adb_path: "/usr/bin/adb",
      address: "127.0.0.1:5555",
    } as PanelLastConnectedDevice
    expect(getStoredDeviceFingerprint(storedAdbFp)).toBe("adb|/usr/bin/adb|127.0.0.1:5555")

    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const storedWin32Fp = { type: "Win32", hWnd: 12345 } as PanelLastConnectedDevice
    expect(getStoredDeviceFingerprint(storedWin32Fp)).toBe("win32|12345")
  })
})

describe("getPlayCoverDefaultAddress", () => {
  it("returns PlayCover capability default_address when present", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const capabilities = [
      { type: "Adb", default_address: "adb-addr" },
      { type: "PlayCover", default_address: "playcover-addr" },
    ] as never[]
    expect(getPlayCoverDefaultAddress(capabilities)).toBe("playcover-addr")
  })
})
