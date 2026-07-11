import type { ExecutionStatus, TriggerConfig, TriggerType } from "@/types/schedulerModel"

function formatCronTrigger(t: (key: string) => string, triggerConfig: TriggerConfig): string {
  if (triggerConfig.type !== "cron") return t("common.unknown")
  return `${t("settings.scheduler.formatter.cron")} ${triggerConfig.cron}`
}

function formatDateTrigger(
  t: (key: string) => string,
  locale: string,
  triggerConfig: TriggerConfig,
): string {
  if (triggerConfig.type !== "date") return t("common.unknown")
  return `${t("settings.scheduler.formatter.date")} ${formatDateTime(t, locale, triggerConfig.run_date)}`
}

function formatIntervalTrigger(t: (key: string) => string, triggerConfig: TriggerConfig): string {
  if (triggerConfig.type !== "interval") return t("common.unknown")
  const parts: string[] = []
  if (triggerConfig.weeks)
    parts.push(`${triggerConfig.weeks}${t("settings.scheduler.formatter.week")}`)
  if (triggerConfig.days)
    parts.push(`${triggerConfig.days}${t("settings.scheduler.formatter.day")}`)
  if (triggerConfig.hours)
    parts.push(`${triggerConfig.hours}${t("settings.scheduler.formatter.hour")}`)
  if (triggerConfig.minutes)
    parts.push(`${triggerConfig.minutes}${t("settings.scheduler.formatter.minute")}`)
  if (triggerConfig.seconds)
    parts.push(`${triggerConfig.seconds}${t("settings.scheduler.formatter.second")}`)
  const intervalText = parts.length > 0 ? parts.join(" ") : t("settings.scheduler.formatter.unset")
  return `${t("settings.scheduler.formatter.interval")} ${intervalText}`
}

export function formatTrigger(
  t: (key: string) => string,
  locale: string,
  triggerType: TriggerType,
  triggerConfig: TriggerConfig,
): string {
  switch (triggerType) {
    case "cron":
      return formatCronTrigger(t, triggerConfig)
    case "date":
      return formatDateTrigger(t, locale, triggerConfig)
    case "interval":
      return formatIntervalTrigger(t, triggerConfig)
    default:
      return t("common.unknown")
  }
}

export function formatDateTime(
  t: (key: string) => string,
  locale: string,
  dateStr?: string,
): string {
  if (!dateStr) return t("settings.scheduler.formatter.unset")
  return new Date(dateStr).toLocaleString(locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function getStatusType(
  status: ExecutionStatus,
): "success" | "error" | "warning" | "info" | "default" {
  switch (status) {
    case "success":
      return "success"
    case "failed":
      return "error"
    case "running":
      return "info"
    case "stopped":
      return "warning"
    default:
      return "default"
  }
}

export function getStatusIcon(status: ExecutionStatus): string {
  switch (status) {
    case "success":
      return "i-mdi-check-circle"
    case "failed":
      return "i-mdi-close-circle"
    case "running":
      return "i-mdi-loading"
    case "stopped":
      return "i-mdi-pause-circle"
    default:
      return "i-mdi-help-circle"
  }
}

export function getStatusLabel(t: (key: string) => string, status: ExecutionStatus): string {
  switch (status) {
    case "success":
      return t("settings.scheduler.status.success")
    case "failed":
      return t("settings.scheduler.status.failed")
    case "running":
      return t("settings.scheduler.status.running")
    case "stopped":
      return t("settings.scheduler.status.stopped")
    default:
      return t("common.unknown")
  }
}
