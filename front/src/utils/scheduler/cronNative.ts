/** A cron part is an integer literal or "*". Lists, ranges, steps, and names
 *  are rejected — mirrors services.native_cron._parse_field accept rules. */
export function isSingleNumberOrStar(part: string): boolean {
  return part === "*" || /^\d+$/.test(part)
}

export interface CronFields {
  minute: number | null
  hour: number | null
  day: number | null
  month: number | null
  dow: number | null
}

/** Convert a cron part to null ("*") or a bounded number. Returns undefined
 *  when the value is outside the allowed range. */
export function toBoundedNumber(
  part: string,
  min: number,
  max: number,
): number | null | undefined {
  if (part === "*") return null
  const n = Number(part)
  if (n < min || n > max) return undefined
  return n
}

/** Parse a 5-field cron into bounded fields. Returns null for invalid format
 *  or any value outside its allowed range. "*" maps to null. */
export function parseCronFields(cron: string): CronFields | null {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return null
  if (!parts.every(isSingleNumberOrStar)) return null

  const minute = toBoundedNumber(parts[0], 0, 59)
  if (minute === undefined) return null
  const hour = toBoundedNumber(parts[1], 0, 23)
  if (hour === undefined) return null
  const day = toBoundedNumber(parts[2], 1, 31)
  if (day === undefined) return null
  const month = toBoundedNumber(parts[3], 1, 12)
  if (month === undefined) return null
  const dow = toBoundedNumber(parts[4], 0, 7)
  if (dow === undefined) return null

  return { minute, hour, day, month, dow }
}

export function hourStarWithOtherRestriction(f: CronFields): boolean {
  if (f.hour !== null) return false
  return f.day !== null || f.month !== null || f.dow !== null
}

export function monthWithoutDay(f: CronFields): boolean {
  return f.month !== null && f.day === null
}

export function dowWithDayOrMonth(f: CronFields): boolean {
  return f.dow !== null && (f.day !== null || f.month !== null)
}

export function dayAndDowRestricted(f: CronFields): boolean {
  return f.day !== null && f.dow !== null
}

/** Native-eligible cron contract (mirrors backend parse_native_cron):
 *  - minute must be concrete
 *  - hour "*" only when day/month/dow are all "*"
 *  - restricted month requires restricted day
 *  - restricted dow requires day and month "*"
 *  - day and dow cannot both be restricted */
export function checkCronNativeEligibility(cron: string): boolean {
  const f = parseCronFields(cron)
  if (!f) return false
  if (f.minute === null) return false
  if (hourStarWithOtherRestriction(f)) return false
  if (monthWithoutDay(f)) return false
  if (dowWithDayOrMonth(f)) return false
  if (dayAndDowRestricted(f)) return false
  return true
}
