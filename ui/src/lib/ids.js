// Stable unique ids for conversations and messages.
//
// Conversations outlive the page (they come back from localStorage), so a
// module-level counter is not enough: after a reload it would restart at 1
// and collide with restored ids. randomUUID is available in every browser
// we target; the counter fallback covers non-secure contexts (plain http on
// a LAN IP), where crypto.randomUUID is undefined.
let fallbackCounter = 0;

export function createId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  fallbackCounter += 1;
  return `id-${Date.now().toString(36)}-${fallbackCounter}`;
}
