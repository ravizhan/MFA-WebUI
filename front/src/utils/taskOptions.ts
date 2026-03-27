import type { Option } from "../types/interface"
import type { TaskOptionValue } from "../types/scheduler"

export function buildOrderedCheckboxValue(option: Extract<Option, { type: "checkbox" }>): string[] {
  const selectedSet = new Set(option.default_case || [])
  return option.cases.filter((item) => selectedSet.has(item.name)).map((item) => item.name)
}

// 根据选项定义生成默认值
export function buildDefaultsFromOptionMap(
  optionMap: Record<string, Option>,
): Record<string, TaskOptionValue> {
  const options: Record<string, TaskOptionValue> = {}
  for (const key in optionMap) {
    const option = optionMap[key]!

    if (option.type === "select" || option.type === "scan_select") {
      const defaultValue = option.default_case ?? option.cases[0]?.name ?? ""
      options[key] = typeof defaultValue === "string" ? defaultValue : ""
      continue
    }

    if (option.type === "input") {
      for (const input of option.inputs) {
        options[`${key}_${input.name}`] = input.default ?? ""
      }
      continue
    }

    if (option.type === "switch") {
      const defaultValue = option.default_case ?? option.cases[0]?.name ?? ""
      options[key] = typeof defaultValue === "string" ? defaultValue : ""
      continue
    }

    if (option.type === "checkbox") {
      options[key] = buildOrderedCheckboxValue(option)
    }
  }

  return options
}

// 仅在提交边界进行兼容转换，内部状态可保留 null 表示“未设置”
export function normalizeOptionValueForBoundary(
  value: TaskOptionValue | null | undefined,
): TaskOptionValue | undefined {
  if (value === undefined) {
    return undefined
  }
  return value === null ? "" : value
}
