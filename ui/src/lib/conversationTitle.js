import { TITLE_MAX_CHARS } from "./historyConfig.js";

// Fallback title for a conversation whose first message is empty or
// unusable — never shown for a normal chat, but the sidebar must never
// render a blank row.
export const UNTITLED_CONVERSATION = "Гарчиггүй яриа";

// Auto-title from the first user question, the way the sidebar labels a
// chat until the user renames it. There is no title-generation model call:
// this is a compliance surface and the title is derived text, not generated
// content. Cuts on a word boundary when one is close enough to the limit so
// a title does not end mid-word.
export function deriveTitle(firstUserText) {
  const collapsed = (firstUserText ?? "").replace(/\s+/g, " ").trim();
  if (!collapsed) return UNTITLED_CONVERSATION;
  if (collapsed.length <= TITLE_MAX_CHARS) return collapsed;

  const clipped = collapsed.slice(0, TITLE_MAX_CHARS);
  const lastSpace = clipped.lastIndexOf(" ");
  // Only honor the word boundary if it keeps most of the budget; otherwise a
  // single long word would collapse the title to a stub.
  const body = lastSpace > TITLE_MAX_CHARS * 0.6 ? clipped.slice(0, lastSpace) : clipped;
  return `${body.trimEnd()}…`;
}
