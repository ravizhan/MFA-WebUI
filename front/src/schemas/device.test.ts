import { describe, expect, it } from "vitest"

import {
  customDeviceAddressSchema,
  ipv4PortSchema,
  playCoverAddressSchema,
  runtimeDeviceAddressSchema,
} from "./device"

describe("ipv4PortSchema", () => {
  it("accepts valid IPv4:port", () => {
    expect(ipv4PortSchema.parse("192.168.1.1:5555")).toBe("192.168.1.1:5555")
  })

  it("trims whitespace", () => {
    expect(ipv4PortSchema.parse(" 10.0.0.1:5555 ")).toBe("10.0.0.1:5555")
  })

  it("canonicalizes leading zeros", () => {
    expect(ipv4PortSchema.parse("192.168.001.001:5555")).toBe("192.168.1.1:5555")
  })

  it("rejects empty", () => {
    expect(ipv4PortSchema.safeParse("").success).toBe(false)
  })

  it("rejects hostname", () => {
    expect(ipv4PortSchema.safeParse("example.com:5555").success).toBe(false)
  })

  it("rejects IPv6", () => {
    expect(ipv4PortSchema.safeParse("::1:5555").success).toBe(false)
  })

  it("rejects URL", () => {
    expect(ipv4PortSchema.safeParse("http://192.168.1.1:5555").success).toBe(false)
  })

  it("rejects missing port", () => {
    expect(ipv4PortSchema.safeParse("192.168.1.1").success).toBe(false)
  })

  it("rejects port 0", () => {
    expect(ipv4PortSchema.safeParse("192.168.1.1:0").success).toBe(false)
  })

  it("rejects port 65536", () => {
    expect(ipv4PortSchema.safeParse("192.168.1.1:65536").success).toBe(false)
  })

  it("accepts port 1", () => {
    expect(ipv4PortSchema.parse("192.168.1.1:1")).toBe("192.168.1.1:1")
  })

  it("accepts port 65535", () => {
    expect(ipv4PortSchema.parse("192.168.1.1:65535")).toBe("192.168.1.1:65535")
  })
})

describe("customDeviceAddressSchema", () => {
  it("accepts Adb with IPv4", () => {
    const r = customDeviceAddressSchema.safeParse({ type: "Adb", address: "10.0.0.1:5555" })
    expect(r.success).toBe(true)
    if (r.success) expect(r.data.address).toBe("10.0.0.1:5555")
  })

  it("rejects Adb with serial", () => {
    expect(
      customDeviceAddressSchema.safeParse({ type: "Adb", address: "emulator-5554" }).success,
    ).toBe(false)
  })

  it("accepts PlayCover with IPv4", () => {
    expect(
      customDeviceAddressSchema.safeParse({ type: "PlayCover", address: "127.0.0.1:1717" }).success,
    ).toBe(true)
  })

  it("accepts Win32 with positive integer", () => {
    const r = customDeviceAddressSchema.safeParse({ type: "Win32", address: "12345" })
    expect(r.success).toBe(true)
    if (r.success) expect(r.data.address).toBe("12345")
  })

  it("rejects Win32 with zero", () => {
    expect(customDeviceAddressSchema.safeParse({ type: "Win32", address: "0" }).success).toBe(false)
  })

  it("accepts Gamepad with hWnd|0", () => {
    const r = customDeviceAddressSchema.safeParse({ type: "Gamepad", address: "12345|0" })
    expect(r.success).toBe(true)
    if (r.success) expect(r.data.address).toBe("12345|0")
  })

  it("accepts Gamepad with hWnd|1", () => {
    expect(
      customDeviceAddressSchema.safeParse({ type: "Gamepad", address: "12345|1" }).success,
    ).toBe(true)
  })

  it("rejects Gamepad with invalid type", () => {
    expect(
      customDeviceAddressSchema.safeParse({ type: "Gamepad", address: "12345|2" }).success,
    ).toBe(false)
  })
})

describe("runtimeDeviceAddressSchema", () => {
  it("accepts Adb with serial", () => {
    const r = runtimeDeviceAddressSchema.safeParse({ type: "Adb", address: "emulator-5554" })
    expect(r.success).toBe(true)
    if (r.success) expect(r.data.address).toBe("emulator-5554")
  })

  it("accepts Adb with IPv4", () => {
    expect(
      runtimeDeviceAddressSchema.safeParse({ type: "Adb", address: "192.168.1.1:5555" }).success,
    ).toBe(true)
  })

  it("rejects Adb with empty", () => {
    expect(runtimeDeviceAddressSchema.safeParse({ type: "Adb", address: "" }).success).toBe(false)
  })

  it("rejects PlayCover with serial", () => {
    expect(
      runtimeDeviceAddressSchema.safeParse({ type: "PlayCover", address: "emulator-5554" }).success,
    ).toBe(false)
  })
})

describe("playCoverAddressSchema", () => {
  it("accepts valid", () => {
    expect(playCoverAddressSchema.parse("127.0.0.1:1717")).toBe("127.0.0.1:1717")
  })

  it("rejects invalid", () => {
    expect(playCoverAddressSchema.safeParse("not-an-ip").success).toBe(false)
  })
})
