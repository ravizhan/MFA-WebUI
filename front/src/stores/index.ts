import { defineStore } from "pinia"

export const useIndexStore = defineStore("index", {
  state: () => {
    return {
      SelectedTaskID: "",
      RunningLog: "",
      Connected: false,
    }
  },
  actions: {
    SelectTask(id: string) {
      this.SelectedTaskID = id
    },
    UpdateLog(log: string) {
      this.RunningLog += log + "\n"
    },
    setConnected(status: boolean) {
      this.Connected = status
    },
  },
})
