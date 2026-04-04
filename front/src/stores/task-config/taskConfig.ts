import { defineStore } from "pinia"
import { getTaskConfig, resetTaskConfig, saveTaskConfig } from "@/services/api"
import { useInterfaceStore } from "@/stores"
import type { Option, PresetTaskOptionValue } from "@/types/interface/model"
import type { TaskExecutionPayload, TaskOptionValue } from "@/types/scheduler/model"
import {
  CUSTOM_PRESET_NAME,
  type PersistedTaskConfig,
  type TaskListItem,
  type TaskPresetSnapshot,
} from "@/types/task-config/model"
import {
  buildDefaultsFromOptionMap,
  normalizeOptionValueForBoundary,
} from "@/utils/task-config/options"

function cloneOptionMap(
  optionMap: Record<string, TaskOptionValue> | null | undefined,
): Record<string, TaskOptionValue> {
  const clonedOptions: Record<string, TaskOptionValue> = {}
  if (!optionMap) {
    return clonedOptions
  }

  for (const [key, value] of Object.entries(optionMap)) {
    clonedOptions[key] = Array.isArray(value) ? [...value] : value
  }
  return clonedOptions
}

function buildTaskCheckedMap(taskList: TaskListItem[]): Record<string, boolean> {
  const taskChecked: Record<string, boolean> = {}
  for (const task of taskList) {
    taskChecked[task.id] = Boolean(task.checked)
  }
  return taskChecked
}

function buildTaskListFromOrder(
  defaultTaskList: TaskListItem[],
  taskOrder: string[] | null | undefined,
  taskChecked: Record<string, boolean>,
): TaskListItem[] {
  if (!taskOrder?.length) {
    return defaultTaskList.map((task) => ({
      ...task,
      checked: taskChecked[task.id] || false,
    }))
  }

  const taskMap = new Map(defaultTaskList.map((task) => [task.id, task]))
  const reorderedTasks: TaskListItem[] = []
  const seenTaskIds = new Set<string>()

  for (const id of taskOrder) {
    const task = taskMap.get(id)
    if (!task || seenTaskIds.has(id)) {
      continue
    }

    reorderedTasks.push({
      id: task.id,
      name: task.name,
      order: task.order,
      checked: taskChecked[id] || false,
    })
    seenTaskIds.add(id)
  }

  for (const task of defaultTaskList) {
    if (seenTaskIds.has(task.id)) {
      continue
    }

    reorderedTasks.push({
      id: task.id,
      name: task.name,
      order: task.order,
      checked: taskChecked[task.id] || false,
    })
  }

  return reorderedTasks
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
    selectedPresetName: CUSTOM_PRESET_NAME,
    presetSnapshots: {} as Record<string, TaskPresetSnapshot>,
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

    buildTaskListFromPersisted(
      taskOrder: string[] | null | undefined,
      taskChecked: Record<string, boolean> | null | undefined,
    ): TaskListItem[] {
      return buildTaskListFromOrder(this.buildDefaultTaskList(), taskOrder, taskChecked || {})
    },

    buildOptionsFromPersisted(
      options: Record<string, TaskOptionValue> | null | undefined,
    ): Record<string, TaskOptionValue> {
      const mergedOptions = this.buildDefaultOptions()

      if (!options) {
        return mergedOptions
      }

      for (const [key, value] of Object.entries(options)) {
        const normalizedValue = normalizeOptionValueForBoundary(
          value as TaskOptionValue | null | undefined,
        )
        if (normalizedValue !== undefined && key in mergedOptions) {
          mergedOptions[key] = normalizedValue
        }
      }

      return mergedOptions
    },

    serializeCurrentSnapshot(): TaskPresetSnapshot {
      const taskOrder = this.taskList.map((task) => task.id)
      const taskChecked = buildTaskCheckedMap(this.taskList)
      const taskOptions: Record<string, TaskOptionValue> = {}

      for (const [key, value] of Object.entries(this.options)) {
        const normalizedValue = normalizeOptionValueForBoundary(
          value as TaskOptionValue | null | undefined,
        )
        if (normalizedValue !== undefined) {
          taskOptions[key] = normalizedValue
        }
      }

      return {
        taskOrder,
        taskChecked,
        taskOptions,
      }
    },

    hydrateSnapshot(snapshot: TaskPresetSnapshot) {
      this.taskList = this.buildTaskListFromPersisted(snapshot.taskOrder, snapshot.taskChecked)
      this.options = this.buildOptionsFromPersisted(snapshot.taskOptions)
    },

    normalizeSnapshot(snapshot?: TaskPresetSnapshot | null): TaskPresetSnapshot {
      const taskList = this.buildTaskListFromPersisted(snapshot?.taskOrder, snapshot?.taskChecked)
      const options = this.buildOptionsFromPersisted(snapshot?.taskOptions)

      return {
        taskOrder: taskList.map((task) => task.id),
        taskChecked: buildTaskCheckedMap(taskList),
        taskOptions: cloneOptionMap(options),
      }
    },

    buildPresetSnapshot(presetName: string): TaskPresetSnapshot | null {
      const interfaceStore = useInterfaceStore()
      const preset = interfaceStore.getPresetByName(presetName)
      if (!preset) {
        return null
      }

      const defaultTaskList = this.buildDefaultTaskList()
      const taskMap = new Map(defaultTaskList.map((task) => [task.id, task]))
      const taskChecked = buildTaskCheckedMap(defaultTaskList)
      const orderedTaskIds: string[] = []
      const usedTaskIds = new Set<string>()
      const optionMap = interfaceStore.interface?.option || {}
      const taskOptions = this.buildDefaultOptions()

      for (const presetTask of preset.task || []) {
        const interfaceTask = interfaceStore.getTaskByName(presetTask.name)
        if (!interfaceTask) {
          continue
        }

        const taskItem = taskMap.get(interfaceTask.entry)
        if (!taskItem || usedTaskIds.has(taskItem.id)) {
          continue
        }

        orderedTaskIds.push(taskItem.id)
        usedTaskIds.add(taskItem.id)
        taskChecked[taskItem.id] = presetTask.enabled ?? true

        for (const [optionName, optionValue] of Object.entries(presetTask.option || {})) {
          applyPresetOptionValue(optionName, optionValue, optionMap, taskOptions)
        }
      }

      for (const task of defaultTaskList) {
        if (!usedTaskIds.has(task.id)) {
          orderedTaskIds.push(task.id)
        }
      }

      return this.normalizeSnapshot({
        taskOrder: orderedTaskIds,
        taskChecked,
        taskOptions,
      })
    },

    seedPresetSnapshots(
      persistedSnapshots: Record<string, TaskPresetSnapshot> = {},
    ): Record<string, TaskPresetSnapshot> {
      const interfaceStore = useInterfaceStore()
      const presetSnapshots: Record<string, TaskPresetSnapshot> = {
        [CUSTOM_PRESET_NAME]: this.normalizeSnapshot(persistedSnapshots[CUSTOM_PRESET_NAME]),
      }

      for (const preset of interfaceStore.getPresetList) {
        presetSnapshots[preset.name] = this.normalizeSnapshot(
          persistedSnapshots[preset.name] || this.buildPresetSnapshot(preset.name),
        )
      }

      return presetSnapshots
    },

    syncCurrentPresetSnapshot() {
      this.presetSnapshots[this.selectedPresetName] = this.serializeCurrentSnapshot()
    },

    selectPreset(presetName: string): boolean {
      const targetPresetName = presetName || CUSTOM_PRESET_NAME
      const targetSnapshot = this.presetSnapshots[targetPresetName]
      if (!targetSnapshot) {
        return false
      }

      if (targetPresetName === this.selectedPresetName) {
        return true
      }

      this.syncCurrentPresetSnapshot()
      this.selectedPresetName = targetPresetName
      this.hydrateSnapshot(targetSnapshot)
      return true
    },

    buildPersistedConfig(): PersistedTaskConfig {
      this.syncCurrentPresetSnapshot()

      const normalizedSnapshots = Object.fromEntries(
        Object.entries(this.presetSnapshots).map(([presetName, snapshot]) => [
          presetName,
          this.normalizeSnapshot(snapshot),
        ]),
      )

      return {
        selectedPreset: this.selectedPresetName,
        presets: normalizedSnapshots,
      }
    },

    async loadConfig() {
      const taskConfig = await getTaskConfig()
      this.presetSnapshots = this.seedPresetSnapshots(taskConfig.presets)

      const selectedPresetName =
        taskConfig.selectedPreset && this.presetSnapshots[taskConfig.selectedPreset]
          ? taskConfig.selectedPreset
          : CUSTOM_PRESET_NAME

      this.selectedPresetName = selectedPresetName
      this.hydrateSnapshot(this.presetSnapshots[this.selectedPresetName]!)
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
      await saveTaskConfig(this.buildPersistedConfig())
    },

    async resetConfig() {
      await resetTaskConfig()
      this.presetSnapshots = this.seedPresetSnapshots()
      this.selectedPresetName = CUSTOM_PRESET_NAME
      this.hydrateSnapshot(this.presetSnapshots[CUSTOM_PRESET_NAME]!)
    },
  },
})
