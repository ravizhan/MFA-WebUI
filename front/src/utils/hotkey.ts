const modifierKeys: Record<string, true> = {
  Control: true,
  Shift: true,
  Alt: true,
  Meta: true,
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
  if (modifierKeys[event.key]) return null

  const parts: string[] = []
  if (event.ctrlKey) parts.push("Ctrl")
  if (event.altKey) parts.push("Alt")
  if (event.shiftKey) parts.push("Shift")
  parts.push(normalizePrimaryKey(event.key))
  return parts.join("+")
}
