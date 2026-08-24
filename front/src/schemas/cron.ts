import { stringToArray, arrayToString } from "cron-converter"
import { z } from "zod"

import { tryCatch } from "@/utils/tryCatch"

const PORTABLE_CRON_ALPHABET = /^[0-9*,\-/\s]+$/
const MONTH_MAX_DAYS = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

/** Normalize and validate a portable cron expression (5-field, ASCII digits only). */
export const cronExpressionSchema = z
  .string()
  .trim()
  .min(1, "cron expression must not be empty")
  .transform((val) => val.replace(/\s+/g, " "))
  .refine((val) => PORTABLE_CRON_ALPHABET.test(val), {
    message: "cron expression contains unsupported characters",
  })
  .refine(
    (val) => {
      const fields = val.split(" ")
      return fields.length === 5
    },
    { message: "cron expression must have 5 fields" },
  )
  .refine(
    (val) => {
      // Month/day feasibility
      const fields = val.split(" ")
      if (fields.length !== 5) return false
      const dayField = fields[2]
      const monthField = fields[3]
      if (dayField === "*" || monthField === "*") return true
      for (const mStr of monthField.split(",")) {
        for (const dStr of dayField.split(",")) {
          const m = Number(mStr)
          const d = Number(dStr)
          if (Number.isNaN(m) || Number.isNaN(d)) continue
          if (m >= 1 && m <= 12 && d > MONTH_MAX_DAYS[m - 1]) return false
        }
      }
      return true
    },
    { message: "invalid month/day combination" },
  )
  .transform((val, ctx) => {
    const [result, err] = tryCatch(() => {
      const arr = stringToArray(val, { enableLastDayOfMonth: false })
      return arrayToString(arr)
    })
    if (err !== null) {
      ctx.addIssue({ code: "custom", message: "invalid cron expression" })
      return z.NEVER
    }
    return result
  })

export type CronExpression = z.output<typeof cronExpressionSchema>

const FULL_MINUTE = new Set(Array.from({ length: 60 }, (_, i) => i))
const FULL_HOUR = new Set(Array.from({ length: 24 }, (_, i) => i))
const FULL_DAY = new Set(Array.from({ length: 31 }, (_, i) => i + 1))
const FULL_MONTH = new Set(Array.from({ length: 12 }, (_, i) => i + 1))
const FULL_DOW = new Set(Array.from({ length: 7 }, (_, i) => i))

function isFullSet(values: number[], full: Set<number>): boolean {
  if (values.length !== full.size) return false
  return values.every((v) => full.has(v))
}

function scalarOrFail(values: number[], full: Set<number>, name: string): number | null {
  if (isFullSet(values, full)) return null
  if (values.length === 1) return values[0]
  throw new Error(`${name} field must be * or a single value for native scheduling`)
}

/** Native (strict subset) cron: single values only, minute required. */
export const nativeCronExpressionSchema = cronExpressionSchema.refine(
  (canonical) => {
    const [result, err] = tryCatch(() => {
      const arr = stringToArray(canonical, { enableLastDayOfMonth: false })
      const [minuteSet, hourSet, daySet, monthSet, dowSet] = arr
      const minute = scalarOrFail(minuteSet, FULL_MINUTE, "minute")
      const hour = scalarOrFail(hourSet, FULL_HOUR, "hour")
      const day = scalarOrFail(daySet, FULL_DAY, "day")
      const month = scalarOrFail(monthSet, FULL_MONTH, "month")
      const dow = scalarOrFail(dowSet, FULL_DOW, "dow")
      if (minute === null) return false
      if (day !== null && dow !== null) return false
      if (hour === null && (day !== null || month !== null || dow !== null)) return false
      if (month !== null && day === null) return false
      if (month !== null && day !== null && day > MONTH_MAX_DAYS[month - 1]) return false
      return true
    })
    return err === null && result === true
  },
  { message: "cron does not meet native scheduling requirements" },
)

export type NativeCronExpression = z.output<typeof nativeCronExpressionSchema>

/** Check if a cron expression is eligible for native (OS-level) scheduling. */
export function checkNativeEligibility(cron: string): boolean {
  return nativeCronExpressionSchema.safeParse(cron).success
}
