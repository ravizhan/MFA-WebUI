import { describe, expect, it } from "vitest"
import {
  buildDefaultsFromOptionMap,
  buildOrderedCheckboxValue,
  normalizeOptionValueForBoundary,
} from "@/utils/task-config/options"
import type { Option } from "@/types/interfaceModel"

describe("buildOrderedCheckboxValue", () => {
  it("preserves case order, filters unknown names, and handles missing default_case", () => {
    expect(
      buildOrderedCheckboxValue({
        type: "checkbox",
        cases: [{ name: "c" }, { name: "a" }, { name: "b" }],
        default_case: ["a", "c"],
      }),
    ).toEqual(["c", "a"])

    expect(
      buildOrderedCheckboxValue({
        type: "checkbox",
        cases: [{ name: "a" }, { name: "b" }],
        default_case: ["a", "c", "b"],
      }),
    ).toEqual(["a", "b"])

    expect(
      buildOrderedCheckboxValue({
        type: "checkbox",
        cases: [{ name: "a" }, { name: "b" }],
      }),
    ).toEqual([])
  })
})

describe("buildDefaultsFromOptionMap", () => {
  it("builds defaults for select/input/switch/checkbox/scan_select branches", () => {
    const optionMap: Record<string, Option> = {
      difficulty: {
        type: "select",
        cases: [{ name: "easy" }, { name: "hard" }],
        default_case: "hard",
      },
      mode: {
        type: "select",
        cases: [{ name: "auto" }, { name: "manual" }],
      },
      empty: {
        type: "select",
        cases: [],
      },
      params: {
        type: "input",
        inputs: [{ name: "host", default: "localhost" }, { name: "port" }],
      },
      toggle: {
        type: "switch",
        cases: [{ name: "off" }, { name: "on" }],
        default_case: "on",
      },
      toggleNoDefault: {
        type: "switch",
        cases: [{ name: "off" }, { name: "on" }],
      },
      features: {
        type: "checkbox",
        cases: [{ name: "a" }, { name: "b" }, { name: "c" }],
        default_case: ["a", "c"],
      },
      tool: {
        type: "scan_select",
        scan_dir: "./tools",
        scan_filter: "*.json",
        cases: [{ name: "hammer" }, { name: "screwdriver" }],
        default_case: "hammer",
      },
    }

    expect(buildDefaultsFromOptionMap(optionMap)).toEqual({
      difficulty: "hard",
      mode: "auto",
      empty: "",
      params: { host: "localhost", port: "" },
      toggle: "on",
      toggleNoDefault: "off",
      features: ["a", "c"],
      tool: "hammer",
    })
  })
})

describe("normalizeOptionValueForBoundary", () => {
  it("normalizes undefined/null/string/array/object boundary values", () => {
    expect(normalizeOptionValueForBoundary(undefined)).toBeUndefined()
    expect(normalizeOptionValueForBoundary(null)).toBe("")
    expect(normalizeOptionValueForBoundary("hello")).toBe("hello")
    expect(normalizeOptionValueForBoundary(["a", "b", "c"])).toEqual(["a", "b", "c"])
    expect(normalizeOptionValueForBoundary({ host: "localhost", port: "8080" })).toEqual({
      host: "localhost",
      port: "8080",
    })
  })
})
