import { REFUSAL_STRING } from "./constants.js";

// Mirrors app/contract.py's is_refusal(): normalize cosmetics, then compare.
// An exact === here disagrees with the backend, which already ships zero
// citations for a drifted refusal — treating such an answer as a real one
// would render a refusal as an ordinary answer with an empty citation
// panel. Deliberately not a substring test: an answer that merely mentions
// the refusal wording and then goes on to answer is a real answer and
// keeps its citations.
function normalizeRefusal(text) {
  // .trim() BEFORE splitting: Python's no-arg str.split() (what
  // app/contract.py's _normalize_refusal uses) discards leading/trailing
  // whitespace as part of splitting, with no empty-string artifacts.
  // /\s+/.split() has no such special case — splitting a string that
  // STARTS with whitespace produces a leading "" element, which .join(" ")
  // then turns into a literal leading space instead of removing it. Left
  // in, that space sits between the string start and a leading quote
  // character, so the quote-stripping regex below (anchored to the true
  // start) never matches — trimming first is what keeps this a faithful
  // port, not just a similar-looking one.
  return text
    .trim()
    .split(/\s+/)
    .join(" ")
    .replace(/^["'«»„“”]+|["'«»„“”]+$/g, "")
    .replace(/\.+$/, "")
    .trim()
    .toLowerCase();
}

export function isRefusal(text) {
  return normalizeRefusal(text) === normalizeRefusal(REFUSAL_STRING);
}
