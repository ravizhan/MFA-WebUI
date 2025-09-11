import { defineStore } from 'pinia'
import { getInterface } from '../script/api'
import type { InterfaceModel } from '../types/interfaceV1'

export interface TaskListItem {
  id: string
  name: string
  order: number
}

export const useInterfaceStore = defineStore('interface', {
  state: () => {
    return {
      interface: null as InterfaceModel | null,
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
      })
    },
  },
})
