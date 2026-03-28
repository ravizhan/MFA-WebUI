import type {
  ScheduledTaskCreate,
  ScheduledTaskUpdate,
  SchedulerApiResponse,
} from "@/types/scheduler/model"

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
