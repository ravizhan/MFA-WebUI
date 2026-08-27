/** Convert datetime-local / ISO string to ISO, or "" if empty/invalid. */
export function toIsoOrEmpty(value: string): string {
  if (!value) return ""
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ""
  return d.toISOString()
}

/** Format ISO string for datetime-local input; "" if missing/invalid. */
export function toDatetimeLocalValue(iso: string | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}
