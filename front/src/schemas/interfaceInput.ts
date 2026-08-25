import { z } from "zod"

import { tryCatch } from "@/utils/tryCatch"

const schemaCache = new Map<string, z.ZodString>()

/** Create a Zod schema for interface option `verify` regex patterns. */
export function makeInterfaceInputSchema(verify: string): z.ZodString {
  const cached = schemaCache.get(verify)
  if (cached) return cached

  const [regex, err] = tryCatch(() => new RegExp(verify))
  if (err !== null || !regex) {
    // Invalid regex in interface.json: allow all input (current compat behavior)
    const schema = z.string()
    schemaCache.set(verify, schema)
    return schema
  }

  const schema = z.string().refine((val) => {
    if (val === "") return true // empty always allowed
    regex.lastIndex = 0 // reset for global/sticky patterns
    return regex.test(val)
  })
  schemaCache.set(verify, schema)
  return schema
}
