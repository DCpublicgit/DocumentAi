// Classifies a failed send into one of a small set of user-facing buckets.
// The kind drives both the Mongolian copy shown in the error bubble
// (App.jsx renders it via errorCopyFor) and whether App.jsx's runAttempt
// spends its one automatic retry on it (isAutoRetryable) — network blips and
// slow/stalled responses are worth one silent retry, a 429 or 5xx from the
// backend is not (retrying instantly into a rate limit or a broken server
// just makes it worse).
export const ERROR_KIND = {
  NETWORK: "network",
  TIMEOUT: "timeout",
  RATE_LIMIT: "rate_limit",
  SERVER: "server",
  UNKNOWN: "unknown",
};

export class ChatRequestError extends Error {
  constructor(kind, message, { status = null, retryAfterSeconds = null } = {}) {
    super(message);
    this.name = "ChatRequestError";
    this.kind = kind;
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

const COPY_BY_KIND = {
  [ERROR_KIND.NETWORK]: "Интернэт холболт тасарсан байна. Холболтоо шалгаад дахин оролдоно уу.",
  [ERROR_KIND.TIMEOUT]: "Хариу удаж байна. Сүлжээ удаашарсан байж магадгүй тул дахин оролдоно уу.",
  [ERROR_KIND.SERVER]: "Серверийн алдаа гарлаа. Түр хүлээгээд дахин оролдоно уу.",
  [ERROR_KIND.UNKNOWN]: "Холболтын алдаа гарлаа. Дахин оролдоно уу.",
};

// Rate limiting gets its own function (not a static string) because the
// copy should say *when* to retry whenever the backend tells us
// (Retry-After), and fall back to a vaguer prompt when it doesn't.
export function errorCopyFor(error) {
  if (error.kind === ERROR_KIND.RATE_LIMIT) {
    const seconds = error.retryAfterSeconds;
    return seconds
      ? `Хэт олон хүсэлт илгээлээ. ${seconds} секундын дараа дахин оролдоно уу.`
      : "Хэт олон хүсэлт илгээлээ. Түр хүлээгээд дахин оролдоно уу.";
  }
  return COPY_BY_KIND[error.kind] ?? COPY_BY_KIND[ERROR_KIND.UNKNOWN];
}

export function isAutoRetryable(kind) {
  return kind === ERROR_KIND.NETWORK || kind === ERROR_KIND.TIMEOUT;
}

// Turns whatever fetch/streamChatCompletion threw into a ChatRequestError.
// streamChat.js already throws ChatRequestError for HTTP-status and
// mid-stream failures (it knows the status code); this only has to handle
// what reaches the catch block un-classified — a bare fetch() rejection.
export function classifyThrown(err) {
  if (err instanceof ChatRequestError) return err;
  if (err instanceof TypeError) {
    // The Fetch spec rejects with TypeError for network failures (offline,
    // DNS failure, connection refused, CORS) — the browser gives no more
    // specific signal than that.
    return new ChatRequestError(ERROR_KIND.NETWORK, err.message);
  }
  return new ChatRequestError(ERROR_KIND.UNKNOWN, err?.message ?? String(err));
}
