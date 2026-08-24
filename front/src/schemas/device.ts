import { z } from "zod"

const ipv4Segment = z
  .string()
  .regex(/^\d{1,3}$/, "invalid IPv4 segment")
  .refine((val) => {
    const n = Number(val)
    return n >= 0 && n <= 255
  }, "IPv4 segment out of range")

/** IPv4:port address schema with canonicalization. */
export const ipv4PortSchema = z
  .string()
  .trim()
  .min(1, "address must not be empty")
  .refine((val) => !val.includes("://") && !val.includes("/"), {
    message: "address must be IPv4:port, not a URL",
  })
  .refine(
    (val) => {
      const idx = val.lastIndexOf(":")
      if (idx <= 0) return false
      const host = val.slice(0, idx)
      const port = val.slice(idx + 1)
      // Check host is valid IPv4
      const parts = host.split(".")
      if (parts.length !== 4) return false
      if (parts.some((part) => !ipv4Segment.safeParse(part).success)) return false
      // Check port
      if (!/^\d+$/.test(port)) return false
      const p = Number(port)
      return p >= 1 && p <= 65535
    },
    { message: "address must be in IPv4:port format" },
  )
  .transform((val) => {
    const idx = val.lastIndexOf(":")
    const host = val.slice(0, idx)
    const port = Number(val.slice(idx + 1))
    // Canonicalize IPv4 (remove leading zeros)
    const canonical = host
      .split(".")
      .map((s) => String(Number(s)))
      .join(".")
    return `${canonical}:${port}`
  })

export type Ipv4Port = z.output<typeof ipv4PortSchema>

const win32AddressSchema = z
  .string()
  .trim()
  .regex(/^\d+$/, "Win32 address must be a positive integer")
  .refine((val) => Number(val) > 0, "hWnd must be positive")
  .transform((val) => String(Number(val)))

const gamepadAddressSchema = z
  .string()
  .trim()
  .regex(/^\d+\|[01]$/, "Gamepad address must be hWnd|type (0 or 1)")
  .refine((val) => {
    const [hwnd] = val.split("|")
    return Number(hwnd) > 0
  }, "Gamepad hWnd must be positive")
  .transform((val) => {
    const [hwnd, type] = val.split("|")
    return `${Number(hwnd)}|${type}`
  })

/** Custom (user-entered) device address: strict validation. */
export const customDeviceAddressSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("Adb"),
    address: ipv4PortSchema,
  }),
  z.object({
    type: z.literal("PlayCover"),
    address: ipv4PortSchema,
  }),
  z.object({
    type: z.literal("Win32"),
    address: win32AddressSchema,
  }),
  z.object({
    type: z.literal("Gamepad"),
    address: gamepadAddressSchema,
  }),
])

export type CustomDeviceAddress = z.output<typeof customDeviceAddressSchema>

/** Runtime (scanned) device address: Adb allows USB serials. */
export const runtimeDeviceAddressSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("Adb"),
    address: z.string().trim().min(1, "Adb address must not be empty"),
  }),
  z.object({
    type: z.literal("PlayCover"),
    address: ipv4PortSchema,
  }),
  z.object({
    type: z.literal("Win32"),
    address: win32AddressSchema,
  }),
  z.object({
    type: z.literal("Gamepad"),
    address: gamepadAddressSchema,
  }),
])

export type RuntimeDeviceAddress = z.output<typeof runtimeDeviceAddressSchema>

/** PlayCover address schema for connection store. */
export const playCoverAddressSchema = ipv4PortSchema

export type PlayCoverAddress = z.output<typeof playCoverAddressSchema>
