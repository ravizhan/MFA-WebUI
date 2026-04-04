import { defineStore } from "pinia"
import { getTaskConfig, resetTaskConfig, saveTaskConfig, type TaskConfig } from "@/services/api"
import { useInterfaceStore } from "@/stores"
import type { Option, PresetTaskOptionValue } from "@/types/interface/model"
import type { TaskExecutionPayload, TaskOptionValue } from "@/types/scheduler/model"
import type { TaskListItem } from "@/types/task-config/model"
import {
  buildDefaultsFromOptionMap,
  normalizeOptionValueForBoundary,
} from "@/utils/task-config/options"

function areTaskListsEquivalent(left: TaskListItem[], right: TaskListItem[]): boolean {
  if (left.length !== right.length) {
    return false
  }

  return left.every((task, index) => {
    const target = right[index]
    return target && task.id === target.id && Boolean(task.checked) === Boolean(target.checked)
  })
}

function areOptionValuesEqual(
  left: TaskOptionValue | undefined,
  right: TaskOptionValue | undefined,
): boolean {
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) {
      return false
    }

    const counts = new Map<string, number>()
    for (const value of left) {
      counts.set(value, (counts.get(value) || 0) + 1)
    }

    for (const value of right) {
      const count = counts.get(value)
      if (!count) {
        return false
      }
      if (count === 1) {
        counts.delete(value)
      } else {
        counts.set(value, count - 1)
      }
    }

    return counts.size === 0
  }
  return left === right
}

function areOptionMapsEquivalent(
  left: Record<string, TaskOptionValue>,
  right: Record<string, TaskOptionValue>,
): boolean {
  const keys = new Set([...Object.keys(left), ...Object.keys(right)])
  for (const key of keys) {
    if (!areOptionValuesEqual(left[key], right[key])) {
      return false
    }
  }
  return true
}

function applyPresetOptionValue(
  optionName: string,
  value: PresetTaskOptionValue,
  optionMap: Record<string, Option>,
  targetOptions: Record<string, TaskOptionValue>,
) {
  const option = optionMap[optionName]
  if (!option) {
    return
  }

  if (option.type === "input") {
    if (typeof value !== "object" || Array.isArray(value) || value === null) {
      return
    }
    const inputValues = value as Record<string, string>
    for (const input of option.inputs) {
      const inputValue = inputValues[input.name]
      if (typeof inputValue === "string") {
        targetOptions[`${optionName}_${input.name}`] = inputValue
      }
    }
    return
  }

  if (option.type === "checkbox") {
    if (Array.isArray(value)) {
      targetOptions[optionName] = value.filter((item): item is string => typeof item === "string")
    }
    return
  }

  if (typeof value === "string") {
    targetOptions[optionName] = value
  }
}

export const useTaskConfigStore = defineStore("taskConfig", {
  state: () => ({
    options: {} as Record<string, TaskOptionValue>,
    taskList: [] as TaskListItem[],
    selectedPresetName: null as string | null,
    presetDirty: false,
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

    buildPresetSnapshot(presetName: string) {
      const interfaceStore = useInterfaceStore()
      const preset = interfaceStore.getPresetByName(presetName)
      if (!preset) {
        return null
      }

      const defaultTaskList = this.buildDefaultTaskList()
      const defaultOptions = this.buildDefaultOptions()
      const taskMap = new Map(defaultTaskList.map((task) => [task.id, task]))
      const orderedTasks: TaskListItem[] = []
      const usedTaskIds = new Set<string>()
      const optionMap = interfaceStore.interface?.option || {}

      for (const presetTask of preset.task || []) {
        const interfaceTask = interfaceStore.getTaskByName(presetTask.name)
        if (!interfaceTask) {
          continue
        }

        const taskItem = taskMap.get(interfaceTask.entry)
        if (!taskItem) {
          continue
        }

        orderedTasks.push({
          ...taskItem,
          checked: presetTask.enabled ?? true,
        })
        usedTaskIds.add(taskItem.id)

        for (const [optionName, optionValue] of Object.entries(presetTask.option || {})) {
          applyPresetOptionValue(optionName, optionValue, optionMap, defaultOptions)
        }
      }

      for (const task of defaultTaskList) {
        if (usedTaskIds.has(task.id)) {
          continue
        }
        orderedTasks.push({
          ...task,
          checked: false,
        })
      }

      return {
        taskList: orderedTasks,
        options: defaultOptions,
      }
    },

    applyPreset(presetName: string): boolean {
      const snapshot = this.buildPresetSnapshot(presetName)
      if (!snapshot) {
        return false
      }

      this.selectedPresetName = presetName
      this.taskList = snapshot.taskList
      this.options = snapshot.options
      this.presetDirty = false
      return true
    },

    clearPreset() {
      this.selectedPresetName = null
      this.presetDirty = false
    },

    reconcilePresetState() {
      if (!this.selectedPresetName) {
        this.presetDirty = false
        return true
      }

      const snapshot = this.buildPresetSnapshot(this.selectedPresetName)
      if (!snapshot) {
        this.clearPreset()
        return false
      }

      this.presetDirty = !(
        areTaskListsEquivalent(this.taskList, snapshot.taskList) &&
        areOptionMapsEquivalent(this.options, snapshot.options)
      )
      return !this.presetDirty
    },

    async loadConfig() {
      const interfaceStore = useInterfaceStore()
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

      const selectedPreset = taskConfig.selectedPreset?.trim()
      this.selectedPresetName =
        selectedPreset && interfaceStore.getPresetByName(selectedPreset) ? selectedPreset : null
      this.presetDirty = Boolean(taskConfig.presetDirty)
      this.reconcilePresetState()
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
        selectedPreset: this.selectedPresetName,
        presetDirty: this.presetDirty,
      }
      await saveTaskConfig(config)
    },

    async resetConfig() {
      await resetTaskConfig()
      this.options = this.buildDefaultOptions()
      this.taskList = this.buildDefaultTaskList()
      this.clearPreset()
    },
  },
})
