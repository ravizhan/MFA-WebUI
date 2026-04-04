import { defineStore } from "pinia"
import {
  getInterface,
  rescanScanSelectOption as requestRescanScanSelectOption,
} from "@/services/api"
import type { InterfaceModel, Option, Preset, Task } from "@/types/interface/model"
import type { TaskListItem } from "@/types/task-config/model"

export const useInterfaceStore = defineStore("interface", {
  state: () => ({
    interface: {} as InterfaceModel,
  }),
  getters: {
    getTaskList: (state) => {
      if (!state.interface?.task) return []
      return state.interface.task.map((item, index) => ({
        id: item.entry,
        name: item.name,
        order: index,
      })) as TaskListItem[]
    },
    getPresetList: (state): Preset[] => state.interface?.preset || [],
  },
  actions: {
    async setInterface() {
      const data = await getInterface()
      this.interface = data
    },

    async rescanScanSelectOption(optionName: string): Promise<boolean> {
      const targetOption = this.interface?.option?.[optionName]
      if (!targetOption || targetOption.type !== "scan_select") {
        return false
      }

      const cases = await requestRescanScanSelectOption(optionName)
      const latestOption = this.interface?.option?.[optionName]
      if (!latestOption || latestOption.type !== "scan_select") {
        return false
      }
      latestOption.cases = cases
      return true
    },

    getTaskByEntry(entry: string): Task | null {
      return this.interface?.task?.find((task) => task.entry === entry) || null
    },

    getTaskByName(name: string): Task | null {
      return this.interface?.task?.find((task) => task.name === name) || null
    },

    getPresetByName(name: string): Preset | null {
      return this.interface?.preset?.find((preset) => preset.name === name) || null
    },

    getOptionList(entry: string): Record<string, Option> {
      const result: Record<string, Option> = {}
      if (!this.interface?.option) return result

      const collectOptions = (optionNames: string[]) => {
        for (const optionName of optionNames) {
          if (result[optionName]) continue
          const optionValue = this.interface.option?.[optionName]
          if (optionValue === undefined) {
            continue
          }
          result[optionName] = optionValue
          for (const caseItem of optionValue.cases || []) {
            if (caseItem.option) {
              collectOptions(caseItem.option)
            }
          }
        }
      }

      const task = this.getTaskByEntry(entry)
      if (task?.option) {
        collectOptions(task.option)
      }
      return result
    },
  },
})
