import { showGlobalMessage } from "../message"
import type { ApiResponse } from "./shared"

interface ResourceResponse {
  status: string
  resource: string[]
}

export function getResource(): Promise<string[]> {
  return fetch("/api/resource", { method: "GET" })
    .then((res) => res.json())
    .then((data: ResourceResponse & ApiResponse) => {
      if (data.status !== "success") {
        showGlobalMessage("error", data.message || "获取资源失败")
        return []
      }
      return data.resource
    })
}

export function postResource(name: string): Promise<boolean> {
  return fetch("/api/resource?name=" + name, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        showGlobalMessage("success", "资源添加成功")
        return true
      }
      showGlobalMessage("error", data.message || "资源设置失败")
      return false
    })
    .catch((error) => {
      console.error("Failed to set resource:", error)
      showGlobalMessage("error", "网络错误，请稍后重试")
      return false
    })
}
