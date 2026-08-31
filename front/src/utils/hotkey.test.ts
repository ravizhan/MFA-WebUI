import { describe, expect, it } from "vitest"

import { buildHotkeyCombo } from "@/utils/hotkey"

describe("buildHotkeyCombo", () => {
  it("orders Ctrl, Alt, and Shift modifiers consistently", () => {
    const event = new KeyboardEvent("keydown", {
      key: "a",
      ctrlKey: true,
      altKey: true,
      shiftKey: true,
    })

    expect(buildHotkeyCombo(event)).toBe("Ctrl+Alt+Shift+A")
  })

  it.each(["Control", "Alt", "Shift", "Meta"])("returns null for a pure %s modifier", (key) => {
    const event = new KeyboardEvent("keydown", { key })

    expect(buildHotkeyCombo(event)).toBeNull()
  })

  it.each([
    ["a", "A"],
    ["z", "Z"],
  ])("uppercases single-character key %s", (key, expected) => {
    const event = new KeyboardEvent("keydown", { key })

    expect(buildHotkeyCombo(event)).toBe(expected)
  })

  it.each([
    ["f1", "F1"],
    ["F12", "F12"],
  ])("normalizes function key %s to %s", (key, expected) => {
    const event = new KeyboardEvent("keydown", { key })

    expect(buildHotkeyCombo(event)).toBe(expected)
  })

  it.each([
    ["ArrowLeft", "Left"],
    ["ArrowRight", "Right"],
    ["ArrowUp", "Up"],
    ["ArrowDown", "Down"],
    ["Escape", "Esc"],
    [" ", "Space"],
    ["Spacebar", "Space"],
  ])("normalizes %s to %s", (key, expected) => {
    const event = new KeyboardEvent("keydown", { key })

    expect(buildHotkeyCombo(event)).toBe(expected)
  })
})
