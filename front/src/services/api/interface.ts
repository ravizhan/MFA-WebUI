import type { InterfaceModel } from "../../types/interface"

export function getInterface(): Promise<InterfaceModel> {
  return fetch("/api/interface", { method: "GET" }).then((res) => res.json())
}
