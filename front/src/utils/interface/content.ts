import type { InterfaceModel } from "@/types/interface/model"

const textFilePattern = /^(?:\.\/)?(?:[^/]+[/])*[^/]+\.(?:md|markdown|txt|html?)$/i

export function isExternalUrl(value: string): boolean {
  return /^(?:https?:)?\/\//i.test(value) || /^(?:data|blob):/i.test(value)
}

export function buildResourceUrl(path: string): string {
  const normalizedPath = path.trim().replace(/\\/g, "/").replace(/^\.\//, "")
  if (normalizedPath === "/resource" || normalizedPath.startsWith("/resource/")) {
    return normalizedPath
  }
  if (normalizedPath === "resource" || normalizedPath.startsWith("resource/")) {
    return `/${normalizedPath}`
  }
  return normalizedPath
}

export function resolveInterfaceText(
  _model: InterfaceModel | null | undefined,
  _locale: string,
  value?: string | null,
  fallback = "",
): string {
  if (value === null || value === undefined) {
    return fallback
  }

  if (value.startsWith("$")) {
    return fallback
  }

  return value
}

export function resolveInterfaceAssetUrl(
  model: InterfaceModel | null | undefined,
  locale: string,
  value?: string | null,
): string | undefined {
  const resolvedValue = resolveInterfaceText(model, locale, value, "").trim()
  if (!resolvedValue) {
    return undefined
  }
  if (isExternalUrl(resolvedValue)) {
    return resolvedValue
  }
  return buildResourceUrl(resolvedValue)
}

export async function resolveInterfaceDocumentContent(
  model: InterfaceModel | null | undefined,
  locale: string,
  value?: string | null,
): Promise<string> {
  const resolvedValue = resolveInterfaceText(model, locale, value, "")
  const trimmedValue = resolvedValue.trim()
  if (!trimmedValue) {
    return ""
  }

  if (isExternalUrl(trimmedValue)) {
    return resolvedValue
  }

  if (!textFilePattern.test(trimmedValue)) {
    return resolvedValue
  }

  const url = buildResourceUrl(trimmedValue)

  try {
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error(`Failed to load interface document: ${trimmedValue}`)
    }
    return await response.text()
  } catch {
    return resolvedValue
  }
}
