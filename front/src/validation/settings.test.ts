import { describe, expect, it } from "vitest"

import {
  darkModeSchema,
  localeSchema,
  makeRuntimeNumberSchema,
  updateChannelSchema,
} from "./settings"

describe("enum schemas", () => {
  it("updateChannelSchema accepts stable", () => {
    expect(updateChannelSchema.safeParse("stable").success).toBe(true)
  })

  it("updateChannelSchema accepts beta", () => {
    expect(updateChannelSchema.safeParse("beta").success).toBe(true)
  })

  it("updateChannelSchema rejects invalid", () => {
    expect(updateChannelSchema.safeParse("alpha").success).toBe(false)
  })

  it("localeSchema accepts zh-CN", () => {
    expect(localeSchema.safeParse("zh-CN").success).toBe(true)
  })

  it("localeSchema accepts en-US", () => {
    expect(localeSchema.safeParse("en-US").success).toBe(true)
  })

  it("darkModeSchema accepts auto", () => {
    expect(darkModeSchema.safeParse("auto").success).toBe(true)
  })

  it("darkModeSchema accepts true", () => {
    expect(darkModeSchema.safeParse(true).success).toBe(true)
  })

  it("darkModeSchema accepts false", () => {
    expect(darkModeSchema.safeParse(false).success).toBe(true)
  })
})

describe("makeRuntimeNumberSchema", () => {
  const schema = makeRuntimeNumberSchema(60, 3600)

  it("returns undefined for empty string", () => {
    expect(schema.parse("")).toBeUndefined()
  })

  it("parses valid number", () => {
    expect(schema.parse("300")).toBe(300)
  })

  it("parses number input", () => {
    expect(schema.parse(300)).toBe(300)
  })

  it("clamps to min", () => {
    expect(schema.parse("10")).toBe(60)
  })

  it("clamps to max", () => {
    expect(schema.parse("9999")).toBe(3600)
  })

  it("returns undefined for NaN", () => {
    expect(schema.parse("abc")).toBeUndefined()
  })
})
