/**
 * Result tuple: [data, null] on success, [null, error] on failure.
 */
type Result<T> = [T, null] | [null, Error]

function toError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error))
}

/**
 * Run a (possibly async) function and return a Result tuple instead of
 * throwing.  Sync usage:  const [data, err] = tryCatch(() => JSON.parse(str))
 * Async usage:            const [data, err] = await tryCatch(() => fetch(url))
 *
 * The eslint config bans raw try/catch in favour of this helper.
 */
export function tryCatch<T>(fn: () => Promise<T>): Promise<Result<T>>
export function tryCatch<T>(fn: () => T): Result<T>
export function tryCatch<T>(fn: () => T | Promise<T>): Result<T> | Promise<Result<T>> {
  // eslint-disable-next-line no-restricted-syntax
  try {
    const result = fn()
    if (result instanceof Promise) {
      return result.then(
        (value: T): Result<T> => [value, null],
        (error: unknown): Result<T> => [null, toError(error)],
      )
    }
    return [result, null]
  } catch (error) {
    return [null, toError(error)]
  }
}
