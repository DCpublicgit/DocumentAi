import { afterEach, describe, expect, it, vi } from "vitest";
import { streamChatCompletion } from "../streamChat.js";
import { ChatRequestError, ERROR_KIND } from "../chatErrors.js";

// Builds a Response-like object whose .body.getReader() replays the given
// SSE text as a single chunk — enough for streamChatCompletion, which only
// calls getReader()/read()/decoder, never anything else on the body.
function fakeStreamResponse({ ok = true, status = 200, headers = {}, sse = "" }) {
  const encoder = new TextEncoder();
  let delivered = false;
  return {
    ok,
    status,
    headers: { get: (name) => headers[name.toLowerCase()] ?? null },
    body: {
      getReader: () => ({
        read: async () => {
          if (delivered) return { done: true, value: undefined };
          delivered = true;
          return { done: false, value: encoder.encode(sse) };
        },
      }),
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamChatCompletion", () => {
  it("streams content-delta tokens to onToken and skips [DONE]", async () => {
    const sse =
      'data: {"choices":[{"delta":{"content":"Сайн"}}]}\n\n' +
      'data: {"choices":[{"delta":{"content":" байна"}}]}\n\n' +
      "data: [DONE]\n\n";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeStreamResponse({ sse })));

    const tokens = [];
    await streamChatCompletion("Асуулт", (t) => tokens.push(t));

    expect(tokens.join("")).toBe("Сайн байна");
  });

  it("delivers a named citations event via onCitations, not onToken", async () => {
    const citations = [{ index: 1, docId: "a.txt" }];
    const sse =
      'data: {"choices":[{"delta":{"content":"Хариулт"}}]}\n\n' +
      `event: citations\ndata: ${JSON.stringify({ citations })}\n\n` +
      "data: [DONE]\n\n";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeStreamResponse({ sse })));

    const tokens = [];
    let received = null;
    await streamChatCompletion("Асуулт", (t) => tokens.push(t), {
      onCitations: (c) => {
        received = c;
      },
    });

    expect(tokens.join("")).toBe("Хариулт");
    expect(received).toEqual(citations);
  });

  it("throws RATE_LIMIT with retryAfterSeconds parsed from the Retry-After header on 429", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        fakeStreamResponse({ ok: false, status: 429, headers: { "retry-after": "20" } }),
      ),
    );

    await expect(streamChatCompletion("Асуулт", () => {})).rejects.toMatchObject({
      kind: ERROR_KIND.RATE_LIMIT,
      retryAfterSeconds: 20,
    });
  });

  it("throws RATE_LIMIT with a null retryAfterSeconds when the header is absent", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeStreamResponse({ ok: false, status: 429 })));

    await expect(streamChatCompletion("Асуулт", () => {})).rejects.toMatchObject({
      kind: ERROR_KIND.RATE_LIMIT,
      retryAfterSeconds: null,
    });
  });

  it("throws SERVER for a 5xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeStreamResponse({ ok: false, status: 503 })));

    await expect(streamChatCompletion("Асуулт", () => {})).rejects.toMatchObject({
      kind: ERROR_KIND.SERVER,
    });
  });

  it("throws UNKNOWN for a non-429/5xx failure status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeStreamResponse({ ok: false, status: 400 })));

    await expect(streamChatCompletion("Асуулт", () => {})).rejects.toMatchObject({
      kind: ERROR_KIND.UNKNOWN,
    });
  });

  it("throws SERVER when the backend ends the stream with a mid-stream error payload", async () => {
    const sse = 'data: {"error":{"message":"LLM provider failed"}}\n\n';
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeStreamResponse({ sse })));

    await expect(streamChatCompletion("Асуулт", () => {})).rejects.toMatchObject({
      kind: ERROR_KIND.SERVER,
    });
  });

  it("propagates a raw fetch rejection (e.g. offline) unclassified — the caller classifies it", async () => {
    const networkError = new TypeError("Failed to fetch");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(networkError));

    await expect(streamChatCompletion("Асуулт", () => {})).rejects.toBe(networkError);
  });

  it("thrown errors are real ChatRequestError instances, not plain objects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeStreamResponse({ ok: false, status: 503 })));

    await expect(streamChatCompletion("Асуулт", () => {})).rejects.toBeInstanceOf(ChatRequestError);
  });
});
