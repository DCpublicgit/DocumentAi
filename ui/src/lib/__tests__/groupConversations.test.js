import { describe, expect, it } from "vitest";
import { filterConversations, groupConversationsByRecency } from "../groupConversations.js";

const NOON = new Date(2026, 7, 14, 12, 0, 0).getTime(); // 2026-08-14, local noon
const DAY = 24 * 60 * 60 * 1000;

function conversation(id, updatedAt, overrides = {}) {
  return {
    id,
    title: `Яриа ${id}`,
    createdAt: updatedAt,
    updatedAt,
    messages: [{ id: `${id}-1`, role: "user", text: "асуулт", kind: "answer", citations: [] }],
    ...overrides,
  };
}

describe("groupConversationsByRecency", () => {
  it("buckets by local calendar day, not by elapsed hours", () => {
    // 23:30 last night is "yesterday" even though it is under 24h ago.
    const lateLastNight = new Date(2026, 7, 13, 23, 30, 0).getTime();
    const groups = groupConversationsByRecency(
      [conversation("a", NOON), conversation("b", lateLastNight)],
      NOON,
    );

    expect(groups.map((group) => group.id)).toEqual(["today", "yesterday"]);
    expect(groups[1].conversations[0].id).toBe("b");
  });

  it("spreads older conversations across the week, month and older buckets", () => {
    const groups = groupConversationsByRecency(
      [
        conversation("week", NOON - 4 * DAY),
        conversation("month", NOON - 20 * DAY),
        conversation("older", NOON - 400 * DAY),
      ],
      NOON,
    );

    expect(groups.map((group) => group.id)).toEqual(["week", "month", "older"]);
  });

  it("omits empty buckets and sorts each bucket newest-first", () => {
    const groups = groupConversationsByRecency(
      [conversation("older", NOON - 3 * 60 * 60 * 1000), conversation("newer", NOON)],
      NOON,
    );

    expect(groups).toHaveLength(1);
    expect(groups[0].conversations.map((c) => c.id)).toEqual(["newer", "older"]);
  });

  it("keeps a future-dated conversation visible instead of dropping it", () => {
    const groups = groupConversationsByRecency([conversation("skewed", NOON + 2 * DAY)], NOON);
    expect(groups[0].id).toBe("today");
  });

  it("returns no groups for an empty history", () => {
    expect(groupConversationsByRecency([], NOON)).toEqual([]);
  });
});

describe("filterConversations", () => {
  const history = [
    conversation("a", NOON, { title: "Цалингийн бодлого" }),
    conversation("b", NOON, {
      title: "Гарчиггүй",
      messages: [
        { id: "b-1", role: "user", text: "Чөлөөний хүсэлт", kind: "answer", citations: [] },
        {
          id: "b-2",
          role: "assistant",
          text: "Хариулт",
          kind: "answer",
          citations: [
            {
              file: "Хөдөлмөрийн дотоод журам.pdf",
              section: "4.1",
              version: "v2",
              effectiveDate: "2026-01-01",
            },
          ],
        },
      ],
    }),
  ];

  it("returns everything for a blank query", () => {
    expect(filterConversations(history, "   ")).toHaveLength(2);
  });

  it("matches the title case-insensitively", () => {
    expect(filterConversations(history, "цалин").map((c) => c.id)).toEqual(["a"]);
  });

  it("matches message text, not just the title", () => {
    expect(filterConversations(history, "чөлөөний").map((c) => c.id)).toEqual(["b"]);
  });

  it("matches a cited policy file name", () => {
    expect(filterConversations(history, "дотоод журам").map((c) => c.id)).toEqual(["b"]);
  });

  it("returns nothing when there is no match", () => {
    expect(filterConversations(history, "тэтгэвэр")).toEqual([]);
  });
});
