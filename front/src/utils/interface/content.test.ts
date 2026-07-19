import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  buildResourceUrl,
  isExternalUrl,
  resolveInterfaceAssetUrl,
  resolveInterfaceDocumentContent,
  resolveInterfaceText,
} from "@/utils/interface/content"
import type { InterfaceModel } from "@/types/interfaceModel"

describe("isExternalUrl", () => {
  it("detects external schemes and rejects relative paths", () => {
    expect(isExternalUrl("https://example.com/file.md")).toBe(true)
    expect(isExternalUrl("//cdn.example.com/file.md")).toBe(true)
    expect(isExternalUrl("data:text/plain,hello")).toBe(true)
    expect(isExternalUrl("blob:uuid-here")).toBe(true)
    expect(isExternalUrl("resource/config.yaml")).toBe(false)
  })
})

describe("buildResourceUrl", () => {
  it("routes resource/ and api/file paths with normalization", () => {
    expect(buildResourceUrl("resource/config.yaml")).toBe("/resource/config.yaml")
    expect(buildResourceUrl("resource")).toBe("/resource")
    expect(buildResourceUrl("images/icon.png")).toBe("/api/file?path=images%2Ficon.png")
    expect(buildResourceUrl("resource\\tools\\cfg.yaml")).toBe("/resource/tools/cfg.yaml")
    expect(buildResourceUrl("  resource/logo.png  ")).toBe("/resource/logo.png")
  })

  it.each([
    "  ",
    "//server/share",
    "/etc/passwd",
    "C:\\Users\\test",
    "../escape",
    "./relative",
    "bad:path",
  ])("rejects invalid path %s", (path) => {
    expect(buildResourceUrl(path)).toBeUndefined()
  })
})

describe("resolveInterfaceText", () => {
  it("returns value or fallback for null/$ tokens", () => {
    expect(resolveInterfaceText(null, "en", "hello")).toBe("hello")
    expect(resolveInterfaceText(null, "en", null, "fallback")).toBe("fallback")
    // $key is a translation token; current impl returns fallback (i18n planned).
    expect(resolveInterfaceText(null, "en", "$dynamic", "fallback")).toBe("fallback")
  })
})

describe("resolveInterfaceAssetUrl", () => {
  // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
  const mockModel = {} as InterfaceModel

  it("returns external URLs as-is and builds resource URLs for relative paths", () => {
    expect(resolveInterfaceAssetUrl(mockModel, "en", "https://example.com/logo.png")).toBe(
      "https://example.com/logo.png",
    )
    expect(resolveInterfaceAssetUrl(mockModel, "en", "resource/logo.png")).toBe(
      "/resource/logo.png",
    )
    expect(resolveInterfaceAssetUrl(mockModel, "en", null)).toBeUndefined()
    expect(resolveInterfaceAssetUrl(mockModel, "en", "  ")).toBeUndefined()
  })
})

describe("resolveInterfaceDocumentContent", () => {
  // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
  const mockModel = {} as InterfaceModel

  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("returns empty/external values without fetching", async () => {
    expect(await resolveInterfaceDocumentContent(mockModel, "en", "")).toBe("")
    expect(
      await resolveInterfaceDocumentContent(mockModel, "en", "https://example.com/doc.md"),
    ).toBe("https://example.com/doc.md")
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it("fetches text document extensions and maps fetch/response errors", async () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("# Hello\nWorld"),
    } as Response)

    expect(await resolveInterfaceDocumentContent(mockModel, "en", "readme.md")).toBe(
      "# Hello\nWorld",
    )
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/file?path=readme.md")

    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("resource content"),
    } as Response)
    expect(await resolveInterfaceDocumentContent(mockModel, "en", "resource/guide.md")).toBe(
      "resource content",
    )
    expect(globalThis.fetch).toHaveBeenCalledWith("/resource/guide.md")

    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("Network error"))
    expect(await resolveInterfaceDocumentContent(mockModel, "en", "doc.txt")).toBe("doc.txt")

    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      text: () => Promise.resolve(""),
    } as Response)
    expect(await resolveInterfaceDocumentContent(mockModel, "en", "broken.md")).toBe("broken.md")
  })

  it("does not fetch non-text extensions or invalid paths", async () => {
    expect(await resolveInterfaceDocumentContent(mockModel, "en", "script.py")).toBe("script.py")
    expect(await resolveInterfaceDocumentContent(mockModel, "en", "../secret.md")).toBe(
      "../secret.md",
    )
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it.each(["doc.md", "doc.markdown", "notes.txt", "page.html", "page.htm"])(
    "treats %s as a fetchable text document",
    async (file) => {
      // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve("content"),
      } as Response)

      expect(await resolveInterfaceDocumentContent(mockModel, "en", file)).toBe("content")
    },
  )
})
