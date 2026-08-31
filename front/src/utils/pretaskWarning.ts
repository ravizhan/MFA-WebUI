const PRETASK_ADVANCED_ACK_KEY = "mwu.pretask.advanced.ack"

export function hasPretaskAck(): boolean {
  return (
    typeof localStorage !== "undefined" && localStorage.getItem(PRETASK_ADVANCED_ACK_KEY) === "1"
  )
}

export function setPretaskAck(): void {
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(PRETASK_ADVANCED_ACK_KEY, "1")
  }
}
