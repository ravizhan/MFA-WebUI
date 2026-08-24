import { describe, expect, it } from "vitest"

import { makeInterfaceInputSchema } from "./interfaceInput"

describe("makeInterfaceInputSchema", () => {
  it("accepts matching input", () => {
    const schema = makeInterfaceInputSchema("^\\d+$")
    expect(schema.safeParse("123").success).toBe(true)
  })

  it("rejects non-matching input", () => {
    const schema = makeInterfaceInputSchema("^\\d+$")
    expect(schema.safeParse("abc").success).toBe(false)
  })

  it("allows empty string", () => {
    const schema = makeInterfaceInputSchema("^\\d+$")
    expect(schema.safeParse("").success).toBe(true)
  })

  it("allows all input for invalid regex", () => {
    const schema = makeInterfaceInputSchema("[invalid")
    expect(schema.safeParse("anything").success).toBe(true)
  })

  it("caches schemas", () => {
    const s1 = makeInterfaceInputSchema("^\\d+$")
    const s2 = makeInterfaceInputSchema("^\\d+$")
    expect(s1).toBe(s2)
  })
})
