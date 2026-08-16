import { describe, expect, it, vi } from "vitest"
import {
  formatTrigger,
  formatDateTime,
  getOriginLabel,
  getStatusType,
  getStatusIcon,
  getStatusLabel,
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

  it("formats cron trigger", () => {
    const config: CronTriggerConfig = { type: "cron", cron: "0 0 * * *" }
    const result = formatTrigger(t, "zh-CN", "cron", config)
    expect(result).toBe("settings.scheduler.formatter.cron 0 0 * * *")
  })

  it("returns unknown when cron config type mismatches", () => {
    const config: IntervalTriggerConfig = { type: "interval", days: 1 }
    const result = formatTrigger(t, "zh-CN", "cron", config)
    expect(result).toBe("common.unknown")
  })

  it("formats date trigger with formatted date", () => {
    const config: DateTriggerConfig = { type: "date", run_date: "2024-06-15T08:30:00Z" }
    const result = formatTrigger(t, "zh-CN", "date", config)
    expect(result).toContain("settings.scheduler.formatter.date")
    expect(result).toContain("2024")
  })

  it("returns unknown when date config type mismatches", () => {
    const config: CronTriggerConfig = { type: "cron", cron: "* * * * *" }
    const result = formatTrigger(t, "zh-CN", "date", config)
    expect(result).toBe("common.unknown")
  })

  it("formats interval with weeks only", () => {
    const config: IntervalTriggerConfig = { type: "interval", weeks: 2 }
    const result = formatTrigger(t, "zh-CN", "interval", config)
    expect(result).toBe("settings.scheduler.formatter.interval 2settings.scheduler.formatter.week")
  })

  it("formats interval with days and hours", () => {
    const config: IntervalTriggerConfig = { type: "interval", days: 1, hours: 2 }
    const result = formatTrigger(t, "zh-CN", "interval", config)
    expect(result).toBe(
      "settings.scheduler.formatter.interval " +
        "1settings.scheduler.formatter.day 2settings.scheduler.formatter.hour",
    )
  })

  it("formats interval with all fields", () => {
    const config: IntervalTriggerConfig = {
      type: "interval",
      weeks: 1,
      days: 2,
      hours: 3,
      minutes: 4,
      seconds: 5,
    }
    const result = formatTrigger(t, "zh-CN", "interval", config)
    expect(result).toBe(
      "settings.scheduler.formatter.interval " +
        "1settings.scheduler.formatter.week " +
        "2settings.scheduler.formatter.day " +
        "3settings.scheduler.formatter.hour " +
        "4settings.scheduler.formatter.minute " +
        "5settings.scheduler.formatter.second",
    )
  })

  it("formats interval with no fields as unset", () => {
    const config: IntervalTriggerConfig = { type: "interval" }
    const result = formatTrigger(t, "zh-CN", "interval", config)
    expect(result).toBe("settings.scheduler.formatter.interval settings.scheduler.formatter.unset")
  })

  it("returns unknown for unknown trigger type", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const result = formatTrigger(t, "zh-CN", "unknown" as never, { type: "cron", cron: "" })
    expect(result).toBe("common.unknown")
  })
})

describe("formatDateTime", () => {
  const t = vi.fn<(key: string) => string>((key: string) => key)

  it("formats valid date string", () => {
    const result = formatDateTime(t, "zh-CN", "2024-06-15T08:30:00Z")
    expect(result).toMatch(/2024/)
    expect(result).toMatch(/06/)
    expect(result).toMatch(/15/)
  })

  it("returns unset for undefined dateStr", () => {
    const result = formatDateTime(t, "zh-CN", undefined)
    expect(result).toBe("settings.scheduler.formatter.unset")
  })

  it("returns unset for empty string", () => {
    const result = formatDateTime(t, "zh-CN", "")
    expect(result).toBe("settings.scheduler.formatter.unset")
  })
})

describe("getStatusType", () => {
  it.each([
    ["success", "success"],
    ["failed", "error"],
    ["running", "info"],
    ["stopped", "warning"],
    ["skipped_busy_manual", "warning"],
    ["skipped_busy_scheduled", "warning"],
    ["skipped_update_in_progress", "warning"],
  ] satisfies [ExecutionStatus, ReturnType<typeof getStatusType>][])(
    "maps %s to %s",
    (status, expected) => {
      expect(getStatusType(status)).toBe(expected)
    },
  )

  it("returns default for unknown status", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(getStatusType("unknown" as ExecutionStatus)).toBe("default")
  })
})

describe("getStatusIcon", () => {
  it.each([
    ["success", "i-mdi-check-circle"],
    ["failed", "i-mdi-close-circle"],
    ["running", "i-mdi-loading"],
    ["stopped", "i-mdi-pause-circle"],
    ["skipped_busy_manual", "i-mdi-account-cancel"],
    ["skipped_busy_scheduled", "i-mdi-calendar-remove"],
    ["skipped_update_in_progress", "i-mdi-update"],
  ] satisfies [ExecutionStatus, string][])("maps %s to %s", (status, expected) => {
    expect(getStatusIcon(status)).toBe(expected)
  })

  it("returns default icon for unknown status", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(getStatusIcon("unknown" as ExecutionStatus)).toBe("i-mdi-help-circle")
  })
})

describe("getStatusLabel", () => {
  const t = vi.fn<(key: string) => string>((key: string) => key)

  it.each([
    ["success", "settings.scheduler.status.success"],
    ["failed", "settings.scheduler.status.failed"],
    ["running", "settings.scheduler.status.running"],
    ["stopped", "settings.scheduler.status.stopped"],
    ["skipped_busy_manual", "settings.scheduler.status.skippedBusyManual"],
    ["skipped_busy_scheduled", "settings.scheduler.status.skippedBusyScheduled"],
    ["skipped_update_in_progress", "settings.scheduler.status.skippedUpdateInProgress"],
  ] satisfies [ExecutionStatus, string][])("maps %s to %s", (status, expected) => {
    expect(getStatusLabel(t, status)).toBe(expected)
  })

  it("returns unknown for unknown status", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(getStatusLabel(t, "unknown" as ExecutionStatus)).toBe("common.unknown")
  })
})

describe("getOriginLabel", () => {
  const t = vi.fn<(key: string) => string>((key: string) => key)

  it.each([
    ["manual", "settings.scheduler.origin.manual"],
    ["in_app", "settings.scheduler.origin.inApp"],
    ["native", "settings.scheduler.origin.native"],
  ] satisfies [ExecutionOrigin, string][])("maps %s to %s", (origin, expected) => {
    expect(getOriginLabel(t, origin)).toBe(expected)
  })

  it("returns unknown for unknown origin", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(getOriginLabel(t, "unknown" as ExecutionOrigin)).toBe("common.unknown")
  })
})
