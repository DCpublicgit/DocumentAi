import { byUpdatedAtDesc } from "./conversationStore.js";

const DAY_MS = 24 * 60 * 60 * 1000;

// Recency buckets, most recent first. `maxAgeDays` is inclusive and counted
// in whole local calendar days, so "Өчигдөр" means yesterday's date — not
// "24 hours ago", which would put this morning's 9am chat in yesterday when
// read at 8am the next day.
const RECENCY_GROUPS = [
  { id: "today", label: "Өнөөдөр", maxAgeDays: 0 },
  { id: "yesterday", label: "Өчигдөр", maxAgeDays: 1 },
  { id: "week", label: "Сүүлийн 7 хоног", maxAgeDays: 7 },
  { id: "month", label: "Сүүлийн 30 хоног", maxAgeDays: 30 },
  { id: "older", label: "Хуучин", maxAgeDays: Infinity },
];

function startOfLocalDay(timestamp) {
  const date = new Date(timestamp);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

// Groups conversations for the sidebar. Returns only non-empty groups, each
// already sorted newest-first, so the list renders straight from this.
export function groupConversationsByRecency(conversations, now = Date.now()) {
  const today = startOfLocalDay(now);
  const buckets = RECENCY_GROUPS.map((group) => ({ ...group, conversations: [] }));

  for (const conversation of [...conversations].sort(byUpdatedAtDesc)) {
    const ageInDays = Math.round((today - startOfLocalDay(conversation.updatedAt)) / DAY_MS);
    // A future timestamp (clock skew, or a machine whose clock was corrected
    // backwards) gives a negative age and lands in "Өнөөдөр" rather than
    // falling out of the list.
    const bucket = buckets.find((candidate) => ageInDays <= candidate.maxAgeDays);
    bucket.conversations.push(conversation);
  }

  return buckets.filter((bucket) => bucket.conversations.length > 0);
}

// Sidebar search. Matches the title and the message text, because the thing
// a user remembers about a past chat is usually a word from the question or
// from the policy answer, not the auto-title. Citations are matched too —
// "Цалингийн журам" is a plausible thing to search for.
export function filterConversations(conversations, query) {
  const needle = query.trim().toLowerCase();
  if (!needle) return conversations;

  return conversations.filter((conversation) => {
    if (conversation.title.toLowerCase().includes(needle)) return true;
    return conversation.messages.some((message) => {
      if (message.text.toLowerCase().includes(needle)) return true;
      return message.citations.some((citation) => citation.file.toLowerCase().includes(needle));
    });
  });
}
