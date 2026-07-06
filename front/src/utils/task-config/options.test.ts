import { describe, expect, it } from "vitest"
import {
  buildDefaultsFromOptionMap,
  buildOrderedCheckboxValue,
  normalizeOptionValueForBoundary,
} from "@/utils/task-config/options"
import type { Option } from "@/types/interface/model"
import type { TaskOptionValue } from "@/types/scheduler/model"

describe("buildOrderedCheckboxValue", () => {
  it("preserves case order, not default_case order", () => {
    // cases: c, a, b — default_case picks "a" and "c"
    // result should follow the *cases* order: c then a
    const option = {
      type: "checkbox",
      cases: [{ name: "c" }, { name: "a" }, { name: "b" }],
      default_case: ["a", "c"],
    } as Option

    const result = buildOrderedCheckboxValue(option as never)
    expect(result).toEqual(["c", "a"])
  })

  it("filters out names not present in cases", () => {
    const option = {
      type: "checkbox",
      cases: [{ name: "a" }, { name: "b" }],
      default_case: ["a", "c", "b"],
    } as Option

    const result = buildOrderedCheckboxValue(option as never)
    expect(result).toEqual(["a", "b"])
  })

  it("handles undefined default_case", () => {
    const option = {
      type: "checkbox",
      cases: [{ name: "a" }, { name: "b" }],
    } as Option

    const result = buildOrderedCheckboxValue(option as never)
    expect(result).toEqual([])
  })
})

describe("buildDefaultsFromOptionMap", () => {
  it("builds defaults for select types", () => {
    const optionMap = {
      difficulty: {
        type: "select",
        cases: [{ name: "easy" }, { name: "hard" }],
        default_case: "hard",
      },
    } as Record<string, Option>

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ difficulty: "hard" })
  })

  it("uses first case when no default_case for select", () => {
    const optionMap = {
      mode: {
        type: "select",
        cases: [{ name: "auto" }, { name: "manual" }],
      },
    } as Record<string, Option>

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ mode: "auto" })
  })

  it("falls back to empty string when default_case is not a string for select", () => {
    // When default_case exists but is not a string (e.g. a number),
    // the typeof guard produces ""
    const optionMap = {
      bad: {
        type: "select",
        cases: [{ name: "a" }, { name: "b" }],
        default_case: 42,
      },
    } as Record<string, Option>

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ bad: "" })
  })

  it("produces empty string when cases array is empty for select", () => {
    const optionMap = {
      empty: {
        type: "select",
        cases: [],
      },
    } as Record<string, Option>

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ empty: "" })
  })

  it("builds defaults for input types", () => {
    const optionMap = {
      params: {
        type: "input",
        inputs: [{ name: "host", default: "localhost" }, { name: "port" }],
      },
    } as Record<string, Option>

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({
      params: { host: "localhost", port: "" },
    })
  })

  it("builds defaults for switch types", () => {
    const optionMap = {
      toggle: {
        type: "switch",
        cases: [{ name: "off" }, { name: "on" }],
        default_case: "on",
      },
    } as Record<string, Option>

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ toggle: "on" })
  })

  it("uses first case when no default_case for switch", () => {
    const optionMap = {
      toggle: {
        type: "switch",
        cases: [{ name: "off" }, { name: "on" }],
      },
    } as Record<string, Option>

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ toggle: "off" })
  })

  it("builds defaults for checkbox types", () => {
    const optionMap = {
      features: {
        type: "checkbox",
        cases: [{ name: "a" }, { name: "b" }, { name: "c" }],
        default_case: ["a", "c"],
      },
    } as Record<string, Option>

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ features: ["a", "c"] })
  })

  it("handles scan_select like select", () => {
    const optionMap = {
      tool: {
        type: "scan_select",
        scan_dir: "./tools",
        scan_filter: "*.json",
        cases: [{ name: "hammer" }, { name: "screwdriver" }],
        default_case: "hammer",
      },
    } as Record<string, Option>

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ tool: "hammer" })
  })
})

describe("normalizeOptionValueForBoundary", () => {
  it("returns undefined for undefined input", () => {
    expect(normalizeOptionValueForBoundary(undefined)).toBeUndefined()
  })

  it("returns empty string for null input", () => {
    expect(normalizeOptionValueForBoundary(null)).toBe("")
  })

  it("passes strings through unchanged", () => {
    expect(normalizeOptionValueForBoundary("hello")).toBe("hello")
  })

  it("filters non-string items from arrays", () => {
    const result = normalizeOptionValueForBoundary(["a", 123, "b", null, "c"] as TaskOptionValue)
    expect(result).toEqual(["a", "b", "c"])
  })

  it("normalizes object values to string record", () => {
    const result = normalizeOptionValueForBoundary({
      host: "localhost",
      port: 8080,
    } as TaskOptionValue)
    expect(result).toEqual({ host: "localhost" })
  })

  it("normalizes malformed persisted non-object to empty record", () => {
    const result = normalizeOptionValueForBoundary(42 as unknown as TaskOptionValue)
    expect(result).toEqual({})
  })
})
