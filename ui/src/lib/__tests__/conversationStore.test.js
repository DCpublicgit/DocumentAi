import { beforeEach, describe, expect, it } from "vitest";
import { loadConversations, saveConversations } from "../conversationStore.js";
import {
  HISTORY_SCHEMA_VERSION,
  HISTORY_STORAGE_KEY,
  MAX_STORED_CONVERSATIONS,
} from "../historyConfig.js";

function writeRaw(payload) {
  window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(payload));
}

function conversation(overrides = {}) {
  return {
    id: "c1",
    title: "Цалингийн бодлого",
    createdAt: 1000,
    updatedAt: 2000,
    messages: [
      { id: "m1", role: "user", text: "Цалин хэзээ олгодог вэ?", kind: "answer", citations: [] },
      {
        id: "m2",
        role: "assistant",
        text: "Сар бүрийн 10-нд.",
        kind: "answer",
        citations: [
          {
            file: "Цалингийн журам.pdf",
            section: "Заалт 3.1: Олголт",
            version: "v2",
            effectiveDate: "2026-01-01",
          },
        ],
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("conversationStore", () => {
  it("round-trips a conversation", () => {
    saveConversations([conversation()]);
    const [restored] = loadConversations();

    expect(restored.id).toBe("c1");
    expect(restored.title).toBe("Цалингийн бодлого");
    expect(restored.messages).toHaveLength(2);
    expect(restored.messages[1].citations[0].file).toBe("Цалингийн журам.pdf");
  });

  it("never restores a message as still streaming", () => {
    saveConversations([
      conversation({
        messages: [
          { id: "m1", role: "assistant", text: "хагас", kind: "answer", citations: [], streaming: true },
        ],
      }),
    ]);

    expect(loadConversations()[0].messages[0].streaming).toBe(false);
  });

  it("returns newest-first regardless of stored order", () => {
    saveConversations([
      conversation({ id: "old", updatedAt: 1 }),
      conversation({ id: "new", updatedAt: 999 }),
    ]);

    expect(loadConversations().map((c) => c.id)).toEqual(["new", "old"]);
  });

  it("keeps only the newest MAX_STORED_CONVERSATIONS", () => {
    const many = Array.from({ length: MAX_STORED_CONVERSATIONS + 5 }, (_, index) =>
      conversation({ id: `c${index}`, updatedAt: index }),
    );
    saveConversations(many);

    const restored = loadConversations();
    expect(restored).toHaveLength(MAX_STORED_CONVERSATIONS);
    expect(restored[0].id).toBe(`c${MAX_STORED_CONVERSATIONS + 4}`);
    expect(restored.some((c) => c.id === "c0")).toBe(false);
  });

  it("reads nothing when storage is empty", () => {
    expect(loadConversations()).toEqual([]);
  });

  it("discards a corrupt payload instead of throwing", () => {
    window.localStorage.setItem(HISTORY_STORAGE_KEY, "{not json");
    expect(loadConversations()).toEqual([]);
  });

  it("discards a payload written by a different schema version", () => {
    writeRaw({ version: HISTORY_SCHEMA_VERSION + 1, conversations: [conversation()] });
    expect(loadConversations()).toEqual([]);
  });

  it("drops malformed records but keeps the valid ones", () => {
    writeRaw({
      version: HISTORY_SCHEMA_VERSION,
      conversations: [
        conversation({ id: "ok" }),
        null,
        { id: "no-title", messages: [] },
        conversation({ id: "no-messages", messages: [] }),
        conversation({ id: "bad-message", messages: [{ role: "system", text: "x" }] }),
      ],
    });

    expect(loadConversations().map((c) => c.id)).toEqual(["ok"]);
  });

  it("gives messages a stable id when the stored payload lacks one", () => {
    writeRaw({
      version: HISTORY_SCHEMA_VERSION,
      conversations: [
        conversation({ messages: [{ role: "user", text: "асуулт", citations: [] }] }),
      ],
    });

    expect(loadConversations()[0].messages[0].id).toBe("c1:0");
  });
});
