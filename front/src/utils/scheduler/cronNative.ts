/**
 * Advisory-only mirror of the backend cron-eligibility check.
 * `services/native_cron.py` is authoritative — it returns HTTP 400 with a precise
 * reason on rejection; this exists solely so the UI can disable the run-when-closed
 * toggle and show a localized hint (runWhenClosedIneligible, en-US.json:177) while
 * the user types, rather than surfacing the backend's hard-coded Chinese 400.
 */
interface CronFields {
  minute: number | null
  hour: number | null
  day: number | null
  month: number | null
  dow: number | null
}

function toBoundedNumber(part: string, min: number, max: number): number | null | undefined {
  if (part === "*") return null
  const n = Number(part)
  if (n < min || n > max) return undefined
  return n
}

function parseCronFields(cron: string): CronFields | null {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return null
  if (!parts.every((p) => p === "*" || /^\d+$/.test(p))) return null
  const minute = toBoundedNumber(parts[0], 0, 59)
  const hour = toBoundedNumber(parts[1], 0, 23)
  const day = toBoundedNumber(parts[2], 1, 31)
  const month = toBoundedNumber(parts[3], 1, 12)
  // dow=7 and dow=0 are equivalent here: both are non-null and the only consumer
  // reads a boolean, so every predicate behaves identically — no 7→0 normalization.
  const dow = toBoundedNumber(parts[4], 0, 7)
  if (minute === undefined || hour === undefined || day === undefined) return null
  if (month === undefined || dow === undefined) return null
  return { minute, hour, day, month, dow }
}

function hourStarWithOtherRestriction(f: CronFields): boolean {
  return f.hour === null && (f.day !== null || f.month !== null || f.dow !== null)
}

/** Restricted dow requires day and month to be "*". This also rejects the
 *  day-and-dow-both-restricted case, so a separate guard for it is unreachable. */
function dowWithDayOrMonth(f: CronFields): boolean {
  return f.dow !== null && (f.day !== null || f.month !== null)
}

/** Native-eligible cron contract (mirrors backend parse_native_cron):
 *  minute concrete, hour "*" only with all-*, restricted month needs day. */
export function checkCronNativeEligibility(cron: string): boolean {
  const f = parseCronFields(cron)
  if (!f) return false
  if (f.minute === null) return false
  if (hourStarWithOtherRestriction(f)) return false
  if (f.month !== null && f.day === null) return false
  if (dowWithDayOrMonth(f)) return false
  return true
}
