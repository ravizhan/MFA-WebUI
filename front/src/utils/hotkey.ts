const modifierKeys: Record<string, true> = {
  Control: true,
  Shift: true,
  Alt: true,
  Meta: true,
}

export type HotkeyCaptureIssue = "meta_unsupported" | "too_many_modifiers"

export function getHotkeyCaptureIssue(event: KeyboardEvent): HotkeyCaptureIssue | null {
  if (event.metaKey) return "meta_unsupported"
  const modifierCount = Number(event.ctrlKey) + Number(event.altKey) + Number(event.shiftKey)
  return modifierCount > 2 ? "too_many_modifiers" : null
}

function normalizePrimaryKey(key: string): string {
  const aliases: Record<string, string> = {
    ArrowLeft: "Left",
    ArrowRight: "Right",
    ArrowUp: "Up",
    ArrowDown: "Down",
    Escape: "Esc",
    " ": "Space",
    Spacebar: "Space",
  }
  if (aliases[key]) return aliases[key]
  if (key.length === 1) return key.toUpperCase()
  if (/^F\d{1,2}$/i.test(key)) return key.toUpperCase()
  return key
}

export function buildHotkeyCombo(event: KeyboardEvent): string | null {
  if (getHotkeyCaptureIssue(event)) return null
  if (modifierKeys[event.key]) return null

  const parts: string[] = []
  if (event.ctrlKey) parts.push("Ctrl")
  if (event.altKey) parts.push("Alt")
  if (event.shiftKey) parts.push("Shift")
  if (parts.length > 2) return null
  parts.push(normalizePrimaryKey(event.key))
  return parts.join("+")
}
