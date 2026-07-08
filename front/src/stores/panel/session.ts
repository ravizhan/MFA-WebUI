import { defineStore } from "pinia"

export const useIndexStore = defineStore("index", {
  state: () => ({
    SelectedTaskID: "",
    RunningLog: "",
    Connected: false,
    TaskRunning: false,
    TaskSettingsDrawerVisible: false,
  }),
  actions: {
    SelectTask(id: string) {
      this.SelectedTaskID = id
    },
    openTaskSettingsDrawer(taskId?: string) {
      if (taskId) {
        this.SelectedTaskID = taskId
      }
      this.TaskSettingsDrawerVisible = true
    },
    closeTaskSettingsDrawer() {
      this.TaskSettingsDrawerVisible = false
    },
    setTaskSettingsDrawerVisible(visible: boolean) {
      this.TaskSettingsDrawerVisible = visible
    },
    UpdateLog(log: string) {
      this.RunningLog += log + "\n"
    },
    setConnected(status: boolean) {
      this.Connected = status
    },
    setTaskRunning(running: boolean) {
      this.TaskRunning = running
    },
  },
})
