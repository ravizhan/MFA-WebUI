/**
 * cron 原生唤醒资格预检。
 *
 * 后端（services/native_cron.py 的 parse_native_cron）为权威，前端仅做可用性预检：
 * 不合格时后端会在创建/更新时返回 400，这里只负责提前禁用唤醒开关。
 *
 * 规则（与后端一致）：
 * - 必须为 5 个字段：minute hour day month dow
 * - 每个字段只允许单个具体整数或 `*`（不支持列表/范围/步进）
 * - minute 必须为具体分钟（非 `*`），保证有确定的唤醒时刻
 * - dow 取值范围 0-7（7 表示周日，与 Unix cron 一致）
 * - day 与 dow 不得同时受限（两者都非 `*`）
 * - hour 为 `*` 时，day/month/dow 必须全为 `*`
 * - month 受限（非 `*`）时，day 必须受限
 */
export function checkCronNativeEligibility(cron: string): boolean {
  const fields = cron.trim().split(/\s+/)
  if (fields.length !== 5) return false

  const [minute, hour, day, month, dow] = fields

  if (fields.some((field) => field !== "*" && !/^\d+$/.test(field))) return false
  if (minute === "*") return false
  if (dow !== "*" && (Number(dow) < 0 || Number(dow) > 7)) return false
  if (day !== "*" && dow !== "*") return false
  if (hour === "*" && (day !== "*" || month !== "*" || dow !== "*")) return false
  if (month !== "*" && day === "*") return false

  return true
}
