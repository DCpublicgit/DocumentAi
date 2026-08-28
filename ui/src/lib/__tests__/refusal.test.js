import { describe, expect, it } from "vitest";
import { isRefusal } from "../refusal.js";
import { REFUSAL_STRING } from "../constants.js";

describe("isRefusal", () => {
  it("matches the exact refusal string", () => {
    expect(isRefusal(REFUSAL_STRING)).toBe(true);
  });

  it("tolerates surrounding whitespace, quotes, and a trailing period", () => {
    expect(isRefusal(`  "${REFUSAL_STRING}"  `)).toBe(true);
    expect(isRefusal(`${REFUSAL_STRING.replace(/\.$/, "")}...`)).toBe(true);
  });

  it("tolerates rewrapped internal whitespace", () => {
    expect(isRefusal(REFUSAL_STRING.replace(/ /g, "\n"))).toBe(true);
  });

  it("is case-insensitive", () => {
    expect(isRefusal(REFUSAL_STRING.toUpperCase())).toBe(true);
  });

  it("is not a substring match — an answer that mentions the refusal wording and then answers is a real answer", () => {
    expect(isRefusal(`${REFUSAL_STRING} Гэхдээ ерөнхийдөө ажлын цаг 40 цаг байдаг.`)).toBe(false);
  });

  it("rejects an ordinary answer", () => {
    expect(isRefusal("Товч хариулт: Ажлын цаг 40 цаг байна.")).toBe(false);
  });
});
