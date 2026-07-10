import type { ApiResponse } from "@/services/api/core/types"

export interface UpdateInfo {
  latest_version: string
  current_version: string
  is_update_available: boolean
  release_notes: string
  download_url: string
  file_hash: string
  file_name: string
  download_source?: "mirrorchyan" | "github"
  update_type?: "full" | "incremental"
}

export interface UpdateCheckResponse {
  status: string
  update_info?: UpdateInfo
  message?: string
}

export interface UpdateStatusResponse {
  status: "idle" | "downloading" | "updating" | "success" | "failed"
  message: string
}

export function checkUpdateApi(): Promise<UpdateCheckResponse> {
  return fetch("/api/update/check", { method: "GET" }).then((res) => res.json())
}

export function performUpdateApi(): Promise<ApiResponse> {
  return fetch("/api/update", { method: "GET" }).then((res) => res.json())
}

export function getUpdateStatusApi(): Promise<UpdateStatusResponse> {
  return fetch("/api/update/status", { method: "GET" }).then((res) => res.json())
}
