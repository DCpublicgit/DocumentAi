import { describe, expect, it } from "vitest";
import { deriveTitle, UNTITLED_CONVERSATION } from "../conversationTitle.js";
import { TITLE_MAX_CHARS } from "../historyConfig.js";

describe("deriveTitle", () => {
  it("uses a short question as-is", () => {
    expect(deriveTitle("Чөлөө хэрхэн авах вэ?")).toBe("Чөлөө хэрхэн авах вэ?");
  });

  it("collapses newlines and repeated spaces", () => {
    expect(deriveTitle("  Цалингийн\n\n  бодлого  ")).toBe("Цалингийн бодлого");
  });

  it("elides a long question at a word boundary", () => {
    const long =
      "Ажилтан жирэмсний амралт авахдаа ямар бичиг баримт бүрдүүлэх шаардлагатай вэ?";
    const title = deriveTitle(long);

    expect(title.length).toBeLessThanOrEqual(TITLE_MAX_CHARS + 1); // + the ellipsis
    expect(title.endsWith("…")).toBe(true);
    expect(title).not.toMatch(/ …$/); // no space left dangling before the ellipsis
    expect(long.startsWith(title.slice(0, -1))).toBe(true);
  });

  it("hard-cuts a single long word rather than returning a stub", () => {
    const oneWord = "а".repeat(TITLE_MAX_CHARS * 2);
    expect(deriveTitle(oneWord)).toBe(`${"а".repeat(TITLE_MAX_CHARS)}…`);
  });

  it("falls back for empty or whitespace-only input", () => {
    expect(deriveTitle("   ")).toBe(UNTITLED_CONVERSATION);
    expect(deriveTitle(undefined)).toBe(UNTITLED_CONVERSATION);
  });
});
