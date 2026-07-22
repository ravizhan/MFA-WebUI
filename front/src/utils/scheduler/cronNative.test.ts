import { describe, expect, it } from "vitest"
import {
  isSingleNumberOrStar,
  parseCronFields,
  checkCronNativeEligibility,
  toBoundedNumber,
} from "@/utils/scheduler/cronNative"

describe("isSingleNumberOrStar", () => {
  it("accepts integers and star", () => {
    expect(isSingleNumberOrStar("*")).toBe(true)
    expect(isSingleNumberOrStar("0")).toBe(true)
    expect(isSingleNumberOrStar("59")).toBe(true)
  })

  it("rejects ranges, lists, steps and names", () => {
    expect(isSingleNumberOrStar("1-5")).toBe(false)
    expect(isSingleNumberOrStar("1,2")).toBe(false)
    expect(isSingleNumberOrStar("*/5")).toBe(false)
    expect(isSingleNumberOrStar("MON")).toBe(false)
    expect(isSingleNumberOrStar("")).toBe(false)
  })
})

describe("toBoundedNumber", () => {
  it("returns null for star and number for valid values", () => {
    expect(toBoundedNumber("*", 0, 59)).toBeNull()
    expect(toBoundedNumber("0", 0, 59)).toBe(0)
    expect(toBoundedNumber("59", 0, 59)).toBe(59)
  })

  it("returns undefined for out-of-range values", () => {
    expect(toBoundedNumber("60", 0, 59)).toBeUndefined()
    expect(toBoundedNumber("-1", 0, 59)).toBeUndefined()
  })
})

describe("parseCronFields", () => {
  it("parses a valid 5-field cron", () => {
    const result = parseCronFields("0 9 * * 1")
    expect(result).toEqual({
      minute: 0,
      hour: 9,
      day: null,
      month: null,
      dow: 1,
    })
  })

  it("returns null for wrong field count", () => {
    expect(parseCronFields("0 9 * *")).toBeNull()
    expect(parseCronFields("0 9 * * * *")).toBeNull()
  })

  it("returns null for unsupported expressions", () => {
    expect(parseCronFields("*/5 * * * *")).toBeNull()
    expect(parseCronFields("0 9 1-15 * *")).toBeNull()
    expect(parseCronFields("0 9 * * MON")).toBeNull()
  })

  it("returns null for values out of range", () => {
    expect(parseCronFields("60 0 * * *")).toBeNull()
    expect(parseCronFields("0 24 * * *")).toBeNull()
    expect(parseCronFields("0 0 32 * *")).toBeNull()
    expect(parseCronFields("0 0 * 13 *")).toBeNull()
    expect(parseCronFields("0 0 * * 8")).toBeNull()
  })
})

describe("checkCronNativeEligibility", () => {
  it("accepts common simple presets", () => {
    expect(checkCronNativeEligibility("0 0 * * *")).toBe(true) // daily
    expect(checkCronNativeEligibility("0 9 * * *")).toBe(true) // daily 9am
    expect(checkCronNativeEligibility("0 0 * * 1")).toBe(true) // weekly Monday
    expect(checkCronNativeEligibility("0 * * * *")).toBe(true) // hourly
  })

  it("requires minute to be concrete", () => {
    expect(checkCronNativeEligibility("* 0 * * *")).toBe(false)
  })

  it("rejects hour=* when any other field is restricted", () => {
    expect(checkCronNativeEligibility("0 * 1 * *")).toBe(false)
    expect(checkCronNativeEligibility("0 * * 1 *")).toBe(false)
    expect(checkCronNativeEligibility("0 * * * 1")).toBe(false)
  })

  it("allows hour=* only when everything else is *", () => {
    expect(checkCronNativeEligibility("0 * * * *")).toBe(true)
  })

  it("rejects month without day", () => {
    expect(checkCronNativeEligibility("0 0 * 1 *")).toBe(false)
  })

  it("allows month when day is also restricted", () => {
    expect(checkCronNativeEligibility("0 0 1 1 *")).toBe(true)
  })

  it("rejects dow with day or month", () => {
    expect(checkCronNativeEligibility("0 0 1 * 1")).toBe(false)
    expect(checkCronNativeEligibility("0 0 * 1 1")).toBe(false)
  })

  it("allows dow only when day and month are *", () => {
    expect(checkCronNativeEligibility("0 0 * * 1")).toBe(true)
  })

  it("rejects when day and dow are both restricted", () => {
    expect(checkCronNativeEligibility("0 0 1 * 1")).toBe(false)
  })

  it("rejects empty or malformed strings", () => {
    expect(checkCronNativeEligibility("")).toBe(false)
    expect(checkCronNativeEligibility("0 0 * *")).toBe(false)
    expect(checkCronNativeEligibility("not a cron")).toBe(false)
  })
})
