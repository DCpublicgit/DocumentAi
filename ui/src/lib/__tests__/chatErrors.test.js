import { describe, expect, it } from "vitest";
import {
  ChatRequestError,
  ERROR_KIND,
  classifyThrown,
  errorCopyFor,
  isAutoRetryable,
} from "../chatErrors.js";

describe("classifyThrown", () => {
  it("passes an existing ChatRequestError through unchanged", () => {
    const err = new ChatRequestError(ERROR_KIND.SERVER, "boom");
    expect(classifyThrown(err)).toBe(err);
  });

  it("classifies a TypeError (fetch's network-failure signal) as NETWORK", () => {
    const classified = classifyThrown(new TypeError("Failed to fetch"));
    expect(classified).toBeInstanceOf(ChatRequestError);
    expect(classified.kind).toBe(ERROR_KIND.NETWORK);
  });

  it("falls back to UNKNOWN for anything else", () => {
    expect(classifyThrown(new Error("mystery")).kind).toBe(ERROR_KIND.UNKNOWN);
    expect(classifyThrown("not even an error").kind).toBe(ERROR_KIND.UNKNOWN);
  });
});

describe("isAutoRetryable", () => {
  it("only network and timeout are auto-retryable", () => {
    expect(isAutoRetryable(ERROR_KIND.NETWORK)).toBe(true);
    expect(isAutoRetryable(ERROR_KIND.TIMEOUT)).toBe(true);
    expect(isAutoRetryable(ERROR_KIND.RATE_LIMIT)).toBe(false);
    expect(isAutoRetryable(ERROR_KIND.SERVER)).toBe(false);
    expect(isAutoRetryable(ERROR_KIND.UNKNOWN)).toBe(false);
  });
});

describe("errorCopyFor", () => {
  it("gives each kind its own copy", () => {
    const network = errorCopyFor(new ChatRequestError(ERROR_KIND.NETWORK, "x"));
    const timeout = errorCopyFor(new ChatRequestError(ERROR_KIND.TIMEOUT, "x"));
    const server = errorCopyFor(new ChatRequestError(ERROR_KIND.SERVER, "x"));
    const unknown = errorCopyFor(new ChatRequestError(ERROR_KIND.UNKNOWN, "x"));

    const copies = new Set([network, timeout, server, unknown]);
    expect(copies.size).toBe(4); // all four distinct — no case collapses into another
  });

  it("mentions the Retry-After seconds when the backend provided one", () => {
    const err = new ChatRequestError(ERROR_KIND.RATE_LIMIT, "x", { retryAfterSeconds: 30 });
    expect(errorCopyFor(err)).toContain("30");
  });

  it("still gives a sensible message when 429 arrives with no Retry-After header", () => {
    const err = new ChatRequestError(ERROR_KIND.RATE_LIMIT, "x", { retryAfterSeconds: null });
    const copy = errorCopyFor(err);
    expect(copy.length).toBeGreaterThan(0);
    expect(copy).not.toContain("null");
  });
});
