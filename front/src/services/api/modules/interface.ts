import type { InterfaceModel, OptionCase } from "@/types/interface/model"
import type { ApiResponse } from "@/services/api/core/types"

export function getInterface(): Promise<InterfaceModel> {
  return fetch("/api/interface", { method: "GET" }).then((res) => res.json())
}

interface ScanSelectRescanResponse extends ApiResponse {
  option_name: string
  cases: OptionCase[]
}

export function rescanScanSelectOption(optionName: string): Promise<OptionCase[]> {
  return fetch("/api/interface/scan-select/rescan", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ option_name: optionName }),
  })
    .then((res) => res.json())
    .then((data: ScanSelectRescanResponse) => {
      if (data.status !== "success" || !Array.isArray(data.cases)) {
        throw new Error(data.message || "重扫 scan_select 失败")
      }
      return data.cases
    })
}
