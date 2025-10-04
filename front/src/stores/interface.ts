import { defineStore } from 'pinia'
import { getInterface } from '../script/api'
import type { InterfaceModel, Option } from '../types/interfaceV1'

export interface TaskListItem {
  id: string
  name: string
  order: number
  checked?: boolean
}

export const useInterfaceStore = defineStore('interface', {
  state: () => {
    return {
      interface: {} as InterfaceModel,
      options: {} as Record<string, string>,
    }
  },
  getters: {
    getTaskList: (state) => {
      if (!state.interface?.task) return []
      const taskList: TaskListItem[] = []
      for (const Item of state.interface.task) {
        taskList.push({
          id: Item.entry,
          name: Item.name,
          order: state.interface.task.indexOf(Item),
        })
      }
      return taskList
    },
  },
  actions: {
    setInterface() {
      getInterface().then((data: InterfaceModel) => {
        this.interface = data
        for (const key in this.interface.option) {
          this.options[key] =
            this.interface.option[key]!.default_case ||
            this.interface.option[key]!['cases'][0]!.name
        }
      })
    },
    getOptionList(entry: string): Record<string, Option> {
      const result: Record<string, Option> = {}
      for (const task of this.interface?.task || []) {
        if (task.entry === entry && task.option) {
          task.option.forEach((optionName) => {
            const optionValue = this.interface?.option[optionName]
            if (optionValue !== undefined) {
              result[optionName] = optionValue
            }
          })
        }
      }
      return result
    },
    setOption(key: string, value: string) {
      this.options[key] = value
    },
  },
})
