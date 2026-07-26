import { describe, expect, it } from "vitest"
import { checkCronNativeEligibility } from "@/utils/scheduler/cronNative"

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
