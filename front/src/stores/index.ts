import { defineStore } from 'pinia'

export const useIndexStore = defineStore('index', {
  state: () => {
    return {
      SelectedTaskID: '',
      RunningLog: '',
    }
  },
  actions: {
    SelectTask(id: string) {
      this.SelectedTaskID = id
    },
    UpdateLog(log: string) {
      this.RunningLog += log + '\n'
    },
  },
})
