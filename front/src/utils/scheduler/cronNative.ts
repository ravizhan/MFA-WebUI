/**
 * cron 原生唤醒资格预检。
 *
 * 后端（services/native_cron.py 的 parse_native_cron）为权威，前端仅做可用性预检：
 * 不合格时后端会在创建/更新时返回 400，这里只负责提前禁用唤醒开关。
 *
 * 规则（与后端一致）：
 * - 必须为 5 个字段：minute hour day month dow
 * - 每个字段只允许单个具体整数或 `*`（不支持列表/范围/步进）
 * - 数值范围：minute 0-59、hour 0-23、day 1-31、month 1-12、dow 0-7（7 表示周日）
 * - minute 必须为具体分钟（非 `*`），保证有确定的唤醒时刻
 * - day 与 dow 不得同时受限（两者都非 `*`）
 * - hour 为 `*` 时，day/month/dow 必须全为 `*`
 * - month 受限（非 `*`）时，day 必须受限
 * - 显式 month+day 组合必须真实存在（如 2 月没有 31 日）
 */

// 各字段取值范围 [min, max]，与后端 _FIELD_RANGES 一致
const FIELD_RANGES: Array<[number, number]> = [
  [0, 59], // minute
  [0, 23], // hour
  [1, 31], // day
  [1, 12], // month
  [0, 7], // dow
]

// 各月最大天数（2 月取 29，与后端一致）
const MAX_DAY_BY_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

export function checkCronNativeEligibility(cron: string): boolean {
  const fields = cron.trim().split(/\s+/)
  if (fields.length !== 5) return false
  // 单字段合法性：`*` 或范围内的单个 ASCII 整数
  const fieldsValid = fields.every((field, i) => {
    if (field === "*") return true
    if (!/^\d+$/.test(field)) return false
    const value = Number(field)
    return value >= FIELD_RANGES[i][0] && value <= FIELD_RANGES[i][1]
  })
  if (!fieldsValid) return false

  const [minute, hour, day, month, dow] = fields
  if (minute === "*") return false
  if (day !== "*" && dow !== "*") return false
  if (hour === "*" && (day !== "*" || month !== "*" || dow !== "*")) return false
  if (month !== "*" && day === "*") return false
  // 显式月+日必须是该月真实存在的日期
  if (month !== "*" && day !== "*" && Number(day) > MAX_DAY_BY_MONTH[Number(month) - 1]) {
    return false
  }

  return true
}
