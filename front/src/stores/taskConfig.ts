import { defineStore } from "pinia"
import { getTaskConfig, saveTaskConfig, resetTaskConfig, type TaskConfig } from "../services/api"
import { type TaskListItem, useInterfaceStore } from "./interface"
import type { Option } from "../types/interface"
import type { TaskExecutionPayload, TaskOptionValue } from "../types/scheduler"

function buildOrderedCheckboxValue(option: Extract<Option, { type: "checkbox" }>): string[] {
  const selectedSet = new Set(option.default_case || [])
  return option.cases.filter((item) => selectedSet.has(item.name)).map((item) => item.name)
}

// 根据选项定义生成默认值
function buildDefaultsFromOptionMap(
  optionMap: Record<string, Option>,
): Record<string, TaskOptionValue> {
  const options: Record<string, TaskOptionValue> = {}
  for (const key in optionMap) {
    const option = optionMap[key]!
    if (option.type === "select" || option.type === "scan_select") {
      options[key] = option.default_case || option.cases[0]?.name || ""
    } else if (option.type === "input") {
      for (const input of option.inputs) {
        options[`${key}_${input.name}`] = input.default || ""
      }
    } else if (option.type === "switch") {
      options[key] = option.default_case || option.cases[0]?.name || ""
    } else if (option.type === "checkbox") {
      options[key] = buildOrderedCheckboxValue(option)
    }
  }
  return options
}

export const useTaskConfigStore = defineStore("taskConfig", {
  state: () => {
    return {
      options: {} as Record<string, TaskOptionValue>,
      taskList: [] as TaskListItem[],
      configLoaded: false,
      saveTimer: null as ReturnType<typeof setTimeout> | null,
    }
  },
  actions: {
    normalizeTaskIds(taskIds: string[]): string[] {
      const interfaceStore = useInterfaceStore()
      const taskSource = this.taskList.length > 0 ? this.taskList : interfaceStore.getTaskList
      const validTaskIds = new Set(taskSource.map((task) => task.id))
      return [...new Set(taskIds)].filter((taskId) => validTaskIds.has(taskId))
    },

    buildDefaultOptions() {
      const interfaceStore = useInterfaceStore()
      const optionMap = interfaceStore.interface?.option || {}
      return buildDefaultsFromOptionMap(optionMap)
    },

    // 根据任务ID列表获取所需的选项（带默认值和用户覆盖）
    buildOptionsForTasks(
      taskIds: string[],
      overrides: Record<string, TaskOptionValue> = {},
    ): Record<string, TaskOptionValue> {
      const interfaceStore = useInterfaceStore()
      const normalizedTaskIds = this.normalizeTaskIds(taskIds)
      const mergedOptionMap: Record<string, Option> = {}

      // 收集所有选中任务的选项
      for (const taskId of normalizedTaskIds) {
        const taskOptions = interfaceStore.getOptionList(taskId)
        Object.assign(mergedOptionMap, taskOptions)
      }

      // 生成默认值
      const defaults = buildDefaultsFromOptionMap(mergedOptionMap)

      // 只过滤出相关的用户配置
      const relevantOptions: Record<string, TaskOptionValue> = {}
      for (const key of Object.keys(defaults)) {
        if (this.options[key] !== undefined) {
          relevantOptions[key] = this.options[key] === null ? "" : this.options[key]
        }
        if (overrides[key] !== undefined) {
          relevantOptions[key] = overrides[key] === null ? "" : overrides[key]
        }
      }

      return {
        ...defaults,
        ...relevantOptions,
      }
    },

    buildExecutionPayload(
      taskIds: string[],
      overrides: Record<string, TaskOptionValue> = {},
    ): TaskExecutionPayload {
      const task_list = this.normalizeTaskIds(taskIds)
      return {
        task_list,
        task_options: this.buildOptionsForTasks(task_list, overrides),
      }
    },

    buildDefaultTaskList() {
      const interfaceStore = useInterfaceStore()
      return interfaceStore.getTaskList.map((task) => ({ ...task, checked: false }))
    },

    async loadConfig() {
      const taskConfig = await getTaskConfig()

      this.options = this.buildDefaultOptions()
      if (taskConfig.taskOptions) {
        Object.assign(this.options, taskConfig.taskOptions)
      }

      const defaultTaskList = this.buildDefaultTaskList()
      this.taskList = defaultTaskList

      if (taskConfig.taskOrder?.length) {
        const taskMap = new Map(defaultTaskList.map((task) => [task.id, task]))
        const taskChecked = taskConfig.taskChecked || {}
        const reorderedTasks: TaskListItem[] = []
        const seenTaskIds = new Set<string>()

        for (const id of taskConfig.taskOrder) {
          const task = taskMap.get(id)
          if (task) {
            reorderedTasks.push({
              id: task.id,
              name: task.name,
              order: task.order,
              checked: taskChecked[id] || false,
            })
            seenTaskIds.add(id)
          }
        }

        for (const task of defaultTaskList) {
          if (!seenTaskIds.has(task.id)) {
            reorderedTasks.push({
              id: task.id,
              name: task.name,
              order: task.order,
              checked: taskChecked[task.id] || false,
            })
          }
        }

        this.taskList = reorderedTasks
      }

      this.configLoaded = true
    },

    debouncedSave() {
      if (this.saveTimer) {
        clearTimeout(this.saveTimer)
      }
      this.saveTimer = setTimeout(() => {
        this.saveConfig()
      }, 500)
    },

    async saveConfig() {
      const taskOrder = this.taskList.map((task) => task.id)
      const taskChecked: Record<string, boolean> = {}
      this.taskList.forEach((task) => {
        taskChecked[task.id] = task.checked || false
      })

      const cleanedOptions: Record<string, TaskOptionValue> = {}
      for (const [key, value] of Object.entries(this.options)) {
        cleanedOptions[key] = value === null ? "" : value
      }

      const config: TaskConfig = {
        taskOrder,
        taskChecked,
        taskOptions: cleanedOptions,
      }
      await saveTaskConfig(config)
    },

    async resetConfig() {
      await resetTaskConfig()
      this.options = this.buildDefaultOptions()
      this.taskList = this.buildDefaultTaskList()
    },
  },
})
