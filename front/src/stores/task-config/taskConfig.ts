import { defineStore } from "pinia"
import { getTaskConfig, resetTaskConfig, saveTaskConfig, type TaskConfig } from "@/services/api"
import { useInterfaceStore } from "@/stores"
import type { Option } from "@/types/interface/model"
import type { TaskExecutionPayload, TaskOptionValue } from "@/types/scheduler/model"
import type { TaskListItem } from "@/types/task-config/model"
import {
  buildDefaultsFromOptionMap,
  normalizeOptionValueForBoundary,
} from "@/utils/task-config/options"

export const useTaskConfigStore = defineStore("taskConfig", {
  state: () => ({
    options: {} as Record<string, TaskOptionValue>,
    taskList: [] as TaskListItem[],
    configLoaded: false,
    saveTimer: null as ReturnType<typeof setTimeout> | null,
  }),
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

    buildOptionsForTasks(
      taskIds: string[],
      overrides: Record<string, TaskOptionValue> = {},
    ): Record<string, TaskOptionValue> {
      const interfaceStore = useInterfaceStore()
      const normalizedTaskIds = this.normalizeTaskIds(taskIds)
      const mergedOptionMap: Record<string, Option> = {}

      for (const taskId of normalizedTaskIds) {
        const taskOptions = interfaceStore.getOptionList(taskId)
        Object.assign(mergedOptionMap, taskOptions)
      }

      const defaults = buildDefaultsFromOptionMap(mergedOptionMap)
      const relevantOptions: Record<string, TaskOptionValue> = {}
      for (const key of Object.keys(defaults)) {
        const currentValue = normalizeOptionValueForBoundary(
          this.options[key] as TaskOptionValue | null | undefined,
        )
        if (currentValue !== undefined) {
          relevantOptions[key] = currentValue
        }

        const overrideValue = normalizeOptionValueForBoundary(
          overrides[key] as TaskOptionValue | null | undefined,
        )
        if (overrideValue !== undefined) {
          relevantOptions[key] = overrideValue
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
        void this.saveConfig()
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
        const normalizedValue = normalizeOptionValueForBoundary(
          value as TaskOptionValue | null | undefined,
        )
        if (normalizedValue !== undefined) {
          cleanedOptions[key] = normalizedValue
        }
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
