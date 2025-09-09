import { defineStore } from 'pinia'

export const useIndexStore = defineStore('index', {
  state: () => {
    return {
      SelectedTaskID: '',
    }
  },
  actions: {
    SelectTask(id: string) {
      this.SelectedTaskID = id
    },
  },
})
