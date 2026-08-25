// Tunables for the chat-history sidebar. Kept in one module so nothing in
// the components carries an inline literal (CONTRIBUTING.md: no hardcoded magic
// numbers), and so a later server-backed history swaps values here.

// localStorage key. Bump HISTORY_SCHEMA_VERSION instead of the key when the
// stored shape changes — loadConversations() drops a mismatched payload
// rather than trying to migrate a pilot's local history.
export const HISTORY_STORAGE_KEY = "policy-chatbot:history";
export const HISTORY_SCHEMA_VERSION = 1;

// Newest-first cap on stored conversations. ~200 users at low volume never
// approach this; the cap exists so one heavy user cannot fill the 5MB
// localStorage quota and start losing writes silently.
export const MAX_STORED_CONVERSATIONS = 100;

// Auto-title length, in characters, before eliding. Sized to the 272px
// sidebar at 0.875rem — longer titles clip visually instead of informing.
export const TITLE_MAX_CHARS = 48;

// Trailing-edge delay on persistence. Streaming patches message state on
// every SSE token; without this we would serialize the whole history to
// localStorage dozens of times per answer.
export const PERSIST_DEBOUNCE_MS = 400;

// Viewport at which the sidebar stops being a persistent column and becomes
// an overlay drawer. Mirrored by the media queries in index.css — keep the
// two in sync.
export const SIDEBAR_BREAKPOINT_PX = 860;
