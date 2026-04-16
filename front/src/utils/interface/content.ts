import type { InterfaceModel } from "@/types/interface/model"

const textFilePattern = /^(?:\.\/)?(?:[^/]+[/])*[^/]+\.(?:md|markdown|txt|html?)$/i

export function isExternalUrl(value: string): boolean {
  return /^(?:https?:)?\/\//i.test(value) || /^(?:data|blob):/i.test(value)
}

function normalizeRootRelativePath(path: string): string | undefined {
  const normalizedPath = path.trim().replace(/\\/g, "/")
  if (!normalizedPath) {
    return undefined
  }

  const parts = normalizedPath.split("/")
  if (parts.some((part) => part.length === 0 || part === "." || part === "..")) {
    return undefined
  }

  return parts.join("/")
}

export function buildResourceUrl(path: string): string {
  const normalizedPath = normalizeRootRelativePath(path)
  if (!normalizedPath) {
    return ""
  }

  if (normalizedPath === "resource" || normalizedPath.startsWith("resource/")) {
    return `/${normalizedPath}`
  }

  return `/api/file?path=${encodeURIComponent(normalizedPath)}`
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
  const url = buildResourceUrl(resolvedValue)
  return url || undefined
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
  if (!url) {
    return resolvedValue
  }

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
