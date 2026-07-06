import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  buildResourceUrl,
  isExternalUrl,
  resolveInterfaceAssetUrl,
  resolveInterfaceDocumentContent,
  resolveInterfaceText,
} from "@/utils/interface/content"
import type { InterfaceModel } from "@/types/interface/model"

describe("isExternalUrl", () => {
  it("detects https:// URLs", () => {
    expect(isExternalUrl("https://example.com/file.md")).toBe(true)
  })

  it("detects protocol-relative URLs", () => {
    expect(isExternalUrl("//cdn.example.com/file.md")).toBe(true)
  })

  it("detects data: URLs", () => {
    expect(isExternalUrl("data:text/plain,hello")).toBe(true)
  })

  it("detects blob: URLs", () => {
    expect(isExternalUrl("blob:uuid-here")).toBe(true)
  })

  it("returns false for relative paths", () => {
    expect(isExternalUrl("resource/config.yaml")).toBe(false)
  })
})

describe("buildResourceUrl", () => {
  it("returns /resource/ path for resource/ prefix", () => {
    expect(buildResourceUrl("resource/config.yaml")).toBe("/resource/config.yaml")
  })

  it("returns /resource for exact resource path", () => {
    expect(buildResourceUrl("resource")).toBe("/resource")
  })

  it("returns /api/file for non-resource paths", () => {
    const result = buildResourceUrl("images/icon.png")
    expect(result).toBe("/api/file?path=images%2Ficon.png")
  })

  it("returns undefined for empty path", () => {
    expect(buildResourceUrl("  ")).toBeUndefined()
  })

  it("returns undefined for UNC paths", () => {
    expect(buildResourceUrl("//server/share")).toBeUndefined()
  })

  it("returns undefined for absolute paths", () => {
    expect(buildResourceUrl("/etc/passwd")).toBeUndefined()
  })

  it("returns undefined for Windows drive paths", () => {
    expect(buildResourceUrl("C:\\Users\\test")).toBeUndefined()
  })

  it("returns undefined for paths containing ..", () => {
    expect(buildResourceUrl("../escape")).toBeUndefined()
  })

  it("returns undefined for paths containing . segments", () => {
    expect(buildResourceUrl("./relative")).toBeUndefined()
  })

  it("returns undefined for paths with colon", () => {
    expect(buildResourceUrl("bad:path")).toBeUndefined()
  })

  it("normalizes backslashes to forward slashes", () => {
    expect(buildResourceUrl("resource\\tools\\cfg.yaml")).toBe("/resource/tools/cfg.yaml")
  })

  it("trims surrounding whitespace", () => {
    expect(buildResourceUrl("  resource/logo.png  ")).toBe("/resource/logo.png")
  })
})

describe("resolveInterfaceText", () => {
  it("returns the value when provided", () => {
    expect(resolveInterfaceText(null, "en", "hello")).toBe("hello")
  })

  it("returns fallback for null value", () => {
    expect(resolveInterfaceText(null, "en", null, "fallback")).toBe("fallback")
  })

  it("returns fallback for $ prefixed translation tokens", () => {
    // $key is a translation/i18n token; the current impl does not resolve
    // translations — returns fallback. Full i18n resolution is planned.
    expect(resolveInterfaceText(null, "en", "$dynamic", "fallback")).toBe("fallback")
  })
})

describe("resolveInterfaceAssetUrl", () => {
  const mockModel = {} as InterfaceModel

  it("returns external URL as-is", () => {
    const result = resolveInterfaceAssetUrl(mockModel, "en", "https://example.com/logo.png")
    expect(result).toBe("https://example.com/logo.png")
  })

  it("returns built resource URL for relative paths", () => {
    const result = resolveInterfaceAssetUrl(mockModel, "en", "resource/logo.png")
    expect(result).toBe("/resource/logo.png")
  })

  it("returns undefined for null/missing values", () => {
    expect(resolveInterfaceAssetUrl(mockModel, "en", null)).toBeUndefined()
  })

  it("trims whitespace before checking", () => {
    expect(resolveInterfaceAssetUrl(mockModel, "en", "  ")).toBeUndefined()
  })
})

describe("resolveInterfaceDocumentContent", () => {
  const mockModel = {} as InterfaceModel

  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("returns empty string for empty value", async () => {
    const result = await resolveInterfaceDocumentContent(mockModel, "en", "")
    expect(result).toBe("")
  })

  it("returns external URL content as-is (not fetched)", async () => {
    const result = await resolveInterfaceDocumentContent(
      mockModel,
      "en",
      "https://example.com/doc.md",
    )
    expect(result).toBe("https://example.com/doc.md")
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it("fetches and returns text for text file paths", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("# Hello\nWorld"),
    } as Response)

    const result = await resolveInterfaceDocumentContent(mockModel, "en", "readme.md")
    expect(result).toBe("# Hello\nWorld")
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/file?path=readme.md")
  })

  it("returns the path itself when fetch fails, proving fetch was called", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("Network error"))

    const result = await resolveInterfaceDocumentContent(mockModel, "en", "doc.txt")
    expect(result).toBe("doc.txt")
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/file?path=doc.txt")
  })

  it("returns the path itself when response is not ok, proving fetch was called", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      text: () => Promise.resolve(""),
    } as Response)

    const result = await resolveInterfaceDocumentContent(mockModel, "en", "broken.md")
    expect(result).toBe("broken.md")
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/file?path=broken.md")
  })

  it("returns value as-is for non-text file extensions", async () => {
    const result = await resolveInterfaceDocumentContent(mockModel, "en", "script.py")
    expect(result).toBe("script.py")
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it.each([
    { ext: ".md", file: "doc.md" },
    { ext: ".markdown", file: "doc.markdown" },
    { ext: ".txt", file: "notes.txt" },
    { ext: ".html", file: "page.html" },
    { ext: ".htm", file: "page.htm" },
  ])("fetches text files with $ext extension", async ({ file }) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("content"),
    } as Response)

    const result = await resolveInterfaceDocumentContent(mockModel, "en", file)
    expect(result).toBe("content")
  })

  it("returns original value and does NOT fetch for invalid ../ paths", async () => {
    const result = await resolveInterfaceDocumentContent(mockModel, "en", "../secret.md")
    // ../secret.md fails normalizeRootRelativePath, so buildResourceUrl returns
    // undefined, and the function returns the resolvedValue without fetching
    expect(result).toBe("../secret.md")
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it("trims whitespace before checking", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("trimmed content"),
    } as Response)

    const result = await resolveInterfaceDocumentContent(mockModel, "en", "  readme.md  ")
    expect(result).toBe("trimmed content")
  })

  it("handles resource/ paths correctly", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("resource content"),
    } as Response)

    const result = await resolveInterfaceDocumentContent(mockModel, "en", "resource/guide.md")
    expect(result).toBe("resource content")
    expect(globalThis.fetch).toHaveBeenCalledWith("/resource/guide.md")
  })
})
