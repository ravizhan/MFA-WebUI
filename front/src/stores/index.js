import { defineStore } from 'pinia'
import { getInterface } from '@/assets/api'

export const useInterfaceStore = defineStore('interface', {
  state: () => ({ interface: null }),
  getters: {
    getTaskList: (state) => {
      if (!state.interface?.task) return []
      const taskList = []
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
      getInterface().then((data) => {
        this.interface = data
      })
    },
  },
})
