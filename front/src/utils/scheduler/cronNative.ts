/**
 * cron 原生唤醒资格预检。
 *
 * 后端（services/native_cron.py 的 parse_native_cron）为权威，前端仅做可用性预检：
 * 不合格时后端会在创建/更新时返回 400，这里只负责提前禁用唤醒开关。
 */

import { nativeCronExpressionSchema } from "@/schemas/cron"

export function checkCronNativeEligibility(cron: string): boolean {
  return nativeCronExpressionSchema.safeParse(cron).success
}
