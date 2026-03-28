import { defineStore } from "pinia"
import {
  getInterface,
  rescanScanSelectOption as requestRescanScanSelectOption,
} from "@/services/api"
import type { InterfaceModel, Option } from "@/types/interface/model"
import type { TaskListItem } from "@/types/task-config/model"

export const useInterfaceStore = defineStore("interface", {
  state: () => ({
    interface: {} as InterfaceModel,
  }),
  getters: {
    getTaskList: (state) => {
      if (!state.interface?.task) return []
      const taskList: TaskListItem[] = []
      for (const item of state.interface.task) {
        taskList.push({
          id: item.entry,
          name: item.name,
          order: state.interface.task.indexOf(item),
        })
      }
      return taskList
    },
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

    getOptionList(entry: string): Record<string, Option> {
      const result: Record<string, Option> = {}
      if (!this.interface?.option) return result

      const collectOptions = (optionNames: string[]) => {
        for (const optionName of optionNames) {
          if (result[optionName]) continue
          const optionValue = this.interface.option?.[optionName]
          if (optionValue !== undefined) {
            result[optionName] = optionValue
            if (
              optionValue.type === "switch" ||
              optionValue.type === "select" ||
              optionValue.type === "scan_select"
            ) {
              for (const caseItem of optionValue.cases) {
                if (caseItem.option) {
                  collectOptions(caseItem.option)
                }
              }
            }
          }
        }
      }

      for (const task of this.interface?.task || []) {
        if (task.entry === entry && task.option) {
          collectOptions(task.option)
        }
      }
      return result
    },
  },
})
