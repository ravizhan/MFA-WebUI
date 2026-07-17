import type {
  ScheduledTaskCreate,
  ScheduledTaskUpdate,
  SchedulerApiResponse,
  SystemTaskCapabilities,
  SystemTaskRegistration,
  SystemTaskRepairResult,
  SystemTaskStatus,
} from "@/types/schedulerModel"

export function getSchedulerTasks(): Promise<SchedulerApiResponse> {
  return fetch("/api/scheduler/tasks", { method: "GET" }).then((res) => res.json())
}

export function createSchedulerTask(task: ScheduledTaskCreate): Promise<SchedulerApiResponse> {
  return fetch("/api/scheduler/tasks", {
    method: "POST",
    body: JSON.stringify(task),
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}

export function updateSchedulerTask(
  taskId: string,
  taskUpdate: ScheduledTaskUpdate,
): Promise<SchedulerApiResponse> {
  return fetch(`/api/scheduler/tasks/${taskId}`, {
    method: "PUT",
    body: JSON.stringify(taskUpdate),
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}

export function deleteSchedulerTask(taskId: string): Promise<SchedulerApiResponse> {
  return fetch(`/api/scheduler/tasks/${taskId}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}

export function pauseSchedulerTask(taskId: string): Promise<SchedulerApiResponse> {
  return fetch(`/api/scheduler/tasks/${taskId}/pause`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}

export function resumeSchedulerTask(taskId: string): Promise<SchedulerApiResponse> {
  return fetch(`/api/scheduler/tasks/${taskId}/resume`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}

export function getSchedulerExecutions(limit: number = 50): Promise<SchedulerApiResponse> {
  return fetch(`/api/scheduler/executions?limit=${limit}`, { method: "GET" }).then((res) =>
    res.json(),
  )
}

export function getSystemTaskStatus(
  taskId: string,
): Promise<{ status: string; data?: SystemTaskStatus; message?: string }> {
  return fetch(`/api/scheduler/tasks/${taskId}/system-status`, {
    method: "GET",
  }).then((res) => res.json())
}

export function getSystemTasks(): Promise<{
  status: string
  registrations?: SystemTaskRegistration[]
  message?: string
}> {
  return fetch("/api/scheduler/system-tasks", { method: "GET" }).then((res) => res.json())
}

export function repairSystemTasks(): Promise<{
  status: string
  data?: SystemTaskRepairResult
  message?: string
}> {
  return fetch("/api/scheduler/system-tasks/repair", { method: "POST" }).then((res) => res.json())
}

export function getSystemCapabilities(): Promise<{
  status: string
  data?: SystemTaskCapabilities
  message?: string
}> {
  return fetch("/api/scheduler/system-capabilities", { method: "GET" }).then((res) => res.json())
}
