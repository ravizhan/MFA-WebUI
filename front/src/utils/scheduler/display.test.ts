import { describe, expect, it, vi } from "vitest"
import {
  formatTrigger,
  formatDateTime,
  getStatusType,
  getStatusIcon,
  getStatusLabel,
  getOriginLabel,
} from "@/utils/scheduler/display"
import type {
  CronTriggerConfig,
  DateTriggerConfig,
  ExecutionOrigin,
  ExecutionStatus,
  IntervalTriggerConfig,
} from "@/types/schedulerModel"

describe("formatTrigger", () => {
  const t = vi.fn<(key: string) => string>((key: string) => key)

  it("formats cron and date triggers, and returns unknown on type mismatch", () => {
    const cron: CronTriggerConfig = { type: "cron", cron: "0 0 * * *" }
    expect(formatTrigger(t, "zh-CN", "cron", cron)).toBe(
      "settings.scheduler.formatter.cron 0 0 * * *",
    )

    const interval: IntervalTriggerConfig = { type: "interval", days: 1 }
    expect(formatTrigger(t, "zh-CN", "cron", interval)).toBe("common.unknown")

    const date: DateTriggerConfig = { type: "date", run_date: "2024-06-15T08:30:00Z" }
    const dateResult = formatTrigger(t, "zh-CN", "date", date)
    expect(dateResult).toContain("settings.scheduler.formatter.date")
    expect(dateResult).toContain("2024")

    expect(formatTrigger(t, "zh-CN", "date", cron)).toBe("common.unknown")
  })

  it("formats interval with fields or unset, and unknown for unknown type", () => {
    expect(formatTrigger(t, "zh-CN", "interval", { type: "interval", weeks: 2 })).toBe(
      "settings.scheduler.formatter.interval 2settings.scheduler.formatter.week",
    )

    expect(
      formatTrigger(t, "zh-CN", "interval", {
        type: "interval",
        weeks: 1,
        days: 2,
        hours: 3,
        minutes: 4,
        seconds: 5,
      }),
    ).toBe(
      "settings.scheduler.formatter.interval " +
        "1settings.scheduler.formatter.week " +
        "2settings.scheduler.formatter.day " +
        "3settings.scheduler.formatter.hour " +
        "4settings.scheduler.formatter.minute " +
        "5settings.scheduler.formatter.second",
    )

    expect(formatTrigger(t, "zh-CN", "interval", { type: "interval" })).toBe(
      "settings.scheduler.formatter.interval settings.scheduler.formatter.unset",
    )

    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(formatTrigger(t, "zh-CN", "unknown" as never, { type: "cron", cron: "" })).toBe(
      "common.unknown",
    )
  })
})

describe("formatDateTime", () => {
  const t = vi.fn<(key: string) => string>((key: string) => key)

  it("formats valid dates and returns unset for missing values", () => {
    const result = formatDateTime(t, "zh-CN", "2024-06-15T08:30:00Z")
    expect(result).toMatch(/2024/)
    expect(result).toMatch(/06/)
    expect(result).toMatch(/15/)
    expect(formatDateTime(t, "zh-CN", undefined)).toBe("settings.scheduler.formatter.unset")
    expect(formatDateTime(t, "zh-CN", "")).toBe("settings.scheduler.formatter.unset")
  })
})

describe("status and origin mapping", () => {
  const t = vi.fn<(key: string) => string>((key: string) => key)

  it("maps representative known statuses and falls back for unknown", () => {
    expect(getStatusType("success")).toBe("success")
    expect(getStatusType("failed")).toBe("error")
    expect(getStatusType("running")).toBe("info")
    expect(getStatusType("skipped_busy_manual")).toBe("warning")
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(getStatusType("unknown" as ExecutionStatus)).toBe("default")

    expect(getStatusIcon("success")).toBe("mdi:check-circle")
    expect(getStatusIcon("failed")).toBe("mdi:close-circle")
    expect(getStatusIcon("missed_deadline")).toBe("mdi:clock-alert")
    expect(getStatusIcon("running")).toBe("mdi:loading")
    expect(getStatusIcon("stopped")).toBe("mdi:pause-circle")
    expect(getStatusIcon("skipped_busy_manual")).toBe("mdi:account-alert")
    expect(getStatusIcon("skipped_busy_scheduled")).toBe("mdi:calendar-alert")
    expect(getStatusIcon("skipped_update_in_progress")).toBe("mdi:update")
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(getStatusIcon("unknown" as ExecutionStatus)).toBe("mdi:help-circle")

    expect(getStatusLabel(t, "success")).toBe("settings.scheduler.status.success")
    expect(getStatusLabel(t, "skipped_busy_scheduled")).toBe(
      "settings.scheduler.status.skipped_busy_scheduled",
    )
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(getStatusLabel(t, "unknown" as ExecutionStatus)).toBe("common.unknown")
  })

  it("maps known origins and falls back for unknown", () => {
    expect(getOriginLabel(t, "manual")).toBe("settings.scheduler.origin.manual")
    expect(getOriginLabel(t, "native")).toBe("settings.scheduler.origin.native")
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(getOriginLabel(t, "unknown" as ExecutionOrigin)).toBe("common.unknown")
  })
})
