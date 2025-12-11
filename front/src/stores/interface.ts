import { defineStore } from 'pinia'
import { getInterface } from '../script/api'
import type { InterfaceModel, Option } from '../types/interfaceV2'

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
          const option = this.interface.option[key]!
          if (option.type === 'select') {
            this.options[key] = option.default_case || ''
          } else if (option.type === 'input') {
            // 为 input 类型的每个输入项设置默认值
            for (const input of option.inputs) {
              this.options[`${key}_${input.name}`] = input.default || ''
            }
          } else if (option.type === 'switch') {
            this.options[key] = option.cases[0]?.name || ''
          }
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
    }
  },
})
