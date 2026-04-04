import i18n from "@/app/i18n"
import type { InterfaceModel } from "@/types/interface/model"

const DOCUMENT_CACHE_MAX_ENTRIES = 100
const DOCUMENT_CACHE_TTL_MS = 10 * 60 * 1000

interface DocumentCacheEntry {
  pending: Promise<string>
  createdAt: number
}

const documentCache = new Map<string, DocumentCacheEntry>()
const textFilePattern = /^(?:\.\/)?(?:[^/]+[/])*[^/]+\.(?:md|markdown|txt|html?)$/i

function cleanupExpiredDocumentCache(now = Date.now()) {
  for (const [url, entry] of documentCache.entries()) {
    if (now - entry.createdAt > DOCUMENT_CACHE_TTL_MS) {
      documentCache.delete(url)
    }
  }
}

function enforceDocumentCacheLimit() {
  while (documentCache.size > DOCUMENT_CACHE_MAX_ENTRIES) {
    const oldestKey = documentCache.keys().next().value as string | undefined
    if (!oldestKey) {
      break
    }
    documentCache.delete(oldestKey)
  }
}

function getValidCachedDocument(url: string, now = Date.now()): Promise<string> | undefined {
  cleanupExpiredDocumentCache(now)

  const cachedEntry = documentCache.get(url)
  if (!cachedEntry) {
    return undefined
  }

  if (now - cachedEntry.createdAt > DOCUMENT_CACHE_TTL_MS) {
    documentCache.delete(url)
    return undefined
  }

  // Refresh insertion order to keep the cache as LRU.
  documentCache.delete(url)
  documentCache.set(url, cachedEntry)
  return cachedEntry.pending
}

function setCachedDocument(url: string, pending: Promise<string>, now = Date.now()) {
  documentCache.set(url, {
    pending,
    createdAt: now,
  })
  enforceDocumentCacheLimit()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function getNestedTranslationValue(
  record: Record<string, unknown>,
  key: string,
): string | undefined {
  const exactValue = record[key]
  if (typeof exactValue === "string") {
    return exactValue
  }

  if (!key.includes(".")) {
    return undefined
  }

  const nestedValue = key.split(".").reduce<unknown>((current, segment) => {
    if (!isRecord(current)) {
      return undefined
    }
    return current[segment]
  }, record)

  return typeof nestedValue === "string" ? nestedValue : undefined
}

function getLocaleCandidates(
  model: InterfaceModel,
  locale: string,
): Array<Record<string, unknown>> {
  const translations = model.translations || {}
  const candidates: Array<Record<string, unknown>> = []
  const seen = new Set<string>()

  const pushLocale = (localeKey: string | undefined) => {
    if (!localeKey || seen.has(localeKey)) {
      return
    }
    const bundle = translations[localeKey]
    if (bundle && isRecord(bundle)) {
      seen.add(localeKey)
      candidates.push(bundle)
    }
  }

  pushLocale(locale)

  const baseLocale = locale.split("-")[0]
  for (const [localeKey, bundle] of Object.entries(translations)) {
    if (localeKey !== locale && localeKey.split("-")[0] === baseLocale && isRecord(bundle)) {
      seen.add(localeKey)
      candidates.push(bundle)
    }
  }

  pushLocale("zh-CN")
  pushLocale("en-US")

  for (const [localeKey, bundle] of Object.entries(translations)) {
    if (seen.has(localeKey) || !isRecord(bundle)) {
      continue
    }
    seen.add(localeKey)
    candidates.push(bundle)
  }

  return candidates
}

export function isExternalUrl(value: string): boolean {
  return /^(?:https?:)?\/\//i.test(value) || /^(?:data|blob):/i.test(value)
}

export function buildResourceUrl(path: string): string {
  const normalizedPath = path.trim().replace(/\\/g, "/").replace(/^\.\//, "")
  if (normalizedPath.startsWith("/resource")) {
    return normalizedPath
  }
  if (normalizedPath.startsWith("resource")) {
    return `/${normalizedPath}`
  }
  return normalizedPath
}

export function resolveInterfaceText(
  model: InterfaceModel | null | undefined,
  locale: string,
  value?: string | null,
  fallback = "",
): string {
  if (value === null || value === undefined) {
    return fallback
  }

  if (!value.startsWith("$")) {
    return value
  }

  const key = value.slice(1)
  if (!key) {
    return fallback
  }

  if (model) {
    for (const bundle of getLocaleCandidates(model, locale)) {
      const translated = getNestedTranslationValue(bundle, key)
      if (translated !== undefined) {
        return translated
      }
    }
  }

  const globalI18n = i18n.global as {
    te?: (key: string, locale?: string) => boolean
    t: (key: string, locale?: string) => string
  }

  if (typeof globalI18n.te === "function" && globalI18n.te(key, locale)) {
    return globalI18n.t(key, locale)
  }

  return key
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

export function invalidateInterfaceDocumentCache(value?: string | null) {
  if (value === null || value === undefined) {
    documentCache.clear()
    return
  }

  const trimmedValue = value.trim()
  if (!trimmedValue) {
    return
  }

  if (isExternalUrl(trimmedValue)) {
    documentCache.delete(trimmedValue)
    return
  }

  documentCache.delete(buildResourceUrl(trimmedValue))
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
    return trimmedValue
  }

  if (!textFilePattern.test(trimmedValue)) {
    return resolvedValue
  }

  const url = buildResourceUrl(trimmedValue)
  let pending = getValidCachedDocument(url)
  if (!pending) {
    pending = fetch(url).then(async (response) => {
      if (!response.ok) {
        throw new Error(`Failed to load interface document: ${trimmedValue}`)
      }
      return response.text()
    })
    setCachedDocument(url, pending)
  }

  try {
    return await pending
  } catch {
    documentCache.delete(url)
    return resolvedValue
  }
}
