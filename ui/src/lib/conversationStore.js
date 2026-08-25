import {
  HISTORY_SCHEMA_VERSION,
  HISTORY_STORAGE_KEY,
  MAX_STORED_CONVERSATIONS,
} from "./historyConfig.js";

/*
  Chat-history persistence for the pre-auth pilot.

  Grain: one row per conversation. Primary key: `id`.
  Record: { id, title, createdAt, updatedAt, messages[] }, where a message is
  { id, role, text, kind, citations[] } — the same shape <Message /> renders,
  minus the transient `streaming` flag.

  Backing store is the browser's localStorage, so history is scoped to a
  browser profile and carries no user identity: there is no sign-in yet.
  When Microsoft/Entra sign-in lands, this module is the only thing that
  changes — same load/save signatures, backed by a per-user server table —
  because nothing above it knows where the rows live.

  Every read is defensive. localStorage is shared with browser extensions,
  can hold a payload written by an older build, and can throw outright
  (Safari private mode, disabled site data). A corrupt or unreadable payload
  degrades to "no history", never to a crashed UI.
*/

function readRaw() {
  try {
    return window.localStorage.getItem(HISTORY_STORAGE_KEY);
  } catch {
    return null;
  }
}

function isNonEmptyString(value) {
  return typeof value === "string" && value.length > 0;
}

function normalizeCitation(raw) {
  if (!raw || typeof raw !== "object") return null;
  const { file, section, version, effectiveDate } = raw;
  if (!isNonEmptyString(file)) return null;
  return {
    file,
    section: typeof section === "string" ? section : "",
    version: typeof version === "string" ? version : "",
    effectiveDate: typeof effectiveDate === "string" ? effectiveDate : "",
  };
}

function normalizeMessage(raw) {
  if (!raw || typeof raw !== "object") return null;
  if (raw.role !== "user" && raw.role !== "assistant") return null;
  if (typeof raw.text !== "string") return null;

  return {
    id: isNonEmptyString(raw.id) ? raw.id : null,
    role: raw.role,
    text: raw.text,
    kind: raw.kind === "refusal" || raw.kind === "error" ? raw.kind : "answer",
    citations: Array.isArray(raw.citations)
      ? raw.citations.map(normalizeCitation).filter(Boolean)
      : [],
    // A reload always lands after the stream ended, so nothing restored from
    // storage is ever mid-stream — the cursor and typing dots must not come
    // back with it.
    streaming: false,
  };
}

function normalizeConversation(raw) {
  if (!raw || typeof raw !== "object") return null;
  if (!isNonEmptyString(raw.id) || !isNonEmptyString(raw.title)) return null;

  const messages = Array.isArray(raw.messages)
    ? raw.messages.map(normalizeMessage).filter(Boolean)
    : [];
  // An empty conversation is unreachable through the UI (a record is only
  // created on the first send) and would render as a dead sidebar row.
  if (messages.length === 0) return null;

  const createdAt = Number.isFinite(raw.createdAt) ? raw.createdAt : Date.now();
  const updatedAt = Number.isFinite(raw.updatedAt) ? raw.updatedAt : createdAt;

  return {
    id: raw.id,
    title: raw.title,
    createdAt,
    updatedAt,
    messages: messages.map((message, index) => ({
      ...message,
      // Older payloads (and hand-edited ones) may lack message ids; derive a
      // stable one from position so React keys and patches still work.
      id: message.id ?? `${raw.id}:${index}`,
    })),
  };
}

export function byUpdatedAtDesc(a, b) {
  return b.updatedAt - a.updatedAt;
}

export function loadConversations() {
  const raw = readRaw();
  if (!raw) return [];

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }

  if (!parsed || parsed.version !== HISTORY_SCHEMA_VERSION || !Array.isArray(parsed.conversations)) {
    return [];
  }

  return parsed.conversations.map(normalizeConversation).filter(Boolean).sort(byUpdatedAtDesc);
}

export function saveConversations(conversations) {
  const payload = {
    version: HISTORY_SCHEMA_VERSION,
    conversations: [...conversations]
      .sort(byUpdatedAtDesc)
      .slice(0, MAX_STORED_CONVERSATIONS)
      .map((conversation) => ({
        ...conversation,
        messages: conversation.messages.map(({ id, role, text, kind, citations }) => ({
          id,
          role,
          text,
          kind,
          citations,
        })),
      })),
  };

  try {
    window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(payload));
    return true;
  } catch {
    // Quota exceeded or storage blocked. The session keeps working from
    // in-memory state; only persistence across reloads is lost.
    return false;
  }
}
