import { describe, expect, it } from "vitest"
import { checkCronNativeEligibility } from "@/utils/scheduler/cronNative"

describe("checkCronNativeEligibility", () => {
  describe("accepts", () => {
    it("daily cron", () => {
      expect(checkCronNativeEligibility("0 9 * * *")).toBe(true)
    })

    it("weekly cron with dow 0", () => {
      expect(checkCronNativeEligibility("30 14 * * 0")).toBe(true)
    })

    it("weekly cron with dow 7", () => {
      expect(checkCronNativeEligibility("30 14 * * 7")).toBe(true)
    })

    it("hourly cron with concrete minute", () => {
      expect(checkCronNativeEligibility("5 * * * *")).toBe(true)
    })

    it("monthly cron on day 15", () => {
      expect(checkCronNativeEligibility("0 9 15 * *")).toBe(true)
    })

    it("month + day cron", () => {
      expect(checkCronNativeEligibility("0 9 15 3 *")).toBe(true)
    })
  })

  describe("rejects", () => {
    it("wildcard minute", () => {
      expect(checkCronNativeEligibility("* * * * *")).toBe(false)
    })

    it("hour wildcard with restricted day", () => {
      expect(checkCronNativeEligibility("0 * 15 * *")).toBe(false)
    })

    it("day and dow both restricted", () => {
      expect(checkCronNativeEligibility("0 9 15 * 1")).toBe(false)
    })

    it("month restricted without day", () => {
      expect(checkCronNativeEligibility("0 9 * 3 *")).toBe(false)
    })

    it("list in minute", () => {
      expect(checkCronNativeEligibility("0,30 9 * * *")).toBe(false)
    })

    it("step in minute", () => {
      expect(checkCronNativeEligibility("*/5 9 * * *")).toBe(false)
    })

    it("range in day", () => {
      expect(checkCronNativeEligibility("0 9 1-5 * *")).toBe(false)
    })

    it("wrong field count", () => {
      expect(checkCronNativeEligibility("0 9 * *")).toBe(false)
      expect(checkCronNativeEligibility("0 9 * * * *")).toBe(false)
    })

    it("empty string", () => {
      expect(checkCronNativeEligibility("")).toBe(false)
    })

    it("out-of-range numeric fields", () => {
      expect(checkCronNativeEligibility("99 9 * * *")).toBe(false)
      expect(checkCronNativeEligibility("0 24 * * *")).toBe(false)
      expect(checkCronNativeEligibility("0 9 0 * *")).toBe(false)
      expect(checkCronNativeEligibility("0 9 32 * *")).toBe(false)
      expect(checkCronNativeEligibility("0 9 15 13 *")).toBe(false)
      expect(checkCronNativeEligibility("99 99 99 99 *")).toBe(false)
    })
  })
})
