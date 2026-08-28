// Turn / token caps on how much prior conversation rides along with a new
// question (see app.retrieve.query_rewrite on the backend, which resolves a
// followup like "Тэгвэл цалинтай юу?" against this history before
// retrieval). A "turn" is one user+assistant exchange, so MAX_HISTORY_TURNS
// caps at twice as many messages. Token count is a cheap chars/4 estimate,
// not a real tokenizer — exact enough to bound payload size without pulling
// a tokenizer into the bundle for a budget that only needs to be roughly
// right.
const MAX_HISTORY_TURNS = 6;
const MAX_HISTORY_TOKENS = 3000;
const CHARS_PER_TOKEN_ESTIMATE = 4;

function estimateTokens(text) {
  return Math.ceil(text.length / CHARS_PER_TOKEN_ESTIMATE);
}

// Builds the `messages` array's history portion — everything BEFORE the new
// question — from the current in-memory conversation's messages
// ({ role, text, kind, citations }, the shape App.jsx's messages state holds).
//
// Drops "error" turns: a connection-failure bubble is UI-side noise, never
// something actually said in the conversation, and would only confuse a
// rewrite/generation call reading it as context. "refusal" turns stay in —
// the model refusing is still a real prior turn a followup can reference
// ("яагаад" — "why not").
//
// Trims from the OLDEST end first under two independent caps (turn count,
// then token budget), so a long-running conversation degrades to "recent
// context only" instead of growing the request without bound. The single
// most recent history entry is always kept even if it alone exceeds the
// token budget — a detailed prior answer easily runs past ~3000 tokens on
// its own, and dropping it entirely would send the very next followup with
// NO context at all, defeating the point for exactly the case that matters
// most (the turn right after a substantial answer).
export function buildHistoryMessages(
  messages,
  { maxTurns = MAX_HISTORY_TURNS, maxTokens = MAX_HISTORY_TOKENS } = {},
) {
  const candidates = messages
    .filter((message) => message.kind !== "error")
    .map((message) => ({ role: message.role, content: message.text }));

  const turnCapped = candidates.slice(-maxTurns * 2);

  let budget = maxTokens;
  const trimmed = [];
  for (let i = turnCapped.length - 1; i >= 0; i--) {
    const cost = estimateTokens(turnCapped[i].content);
    if (trimmed.length > 0 && cost > budget) break;
    trimmed.unshift(turnCapped[i]);
    budget -= cost;
  }
  return trimmed;
}
