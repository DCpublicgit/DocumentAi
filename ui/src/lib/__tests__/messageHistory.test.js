import { describe, expect, it } from "vitest";
import { buildHistoryMessages } from "../messageHistory.js";

function message(role, text, overrides = {}) {
  return { id: `${role}-${text.slice(0, 8)}`, role, text, kind: "answer", citations: [], ...overrides };
}

describe("buildHistoryMessages", () => {
  it("converts stored messages into plain {role, content} entries", () => {
    const result = buildHistoryMessages([
      message("user", "Жирэмсний амралт хэдэн хоног вэ?"),
      message("assistant", "Жирэмсний амралт 120 хоног байна."),
    ]);

    expect(result).toEqual([
      { role: "user", content: "Жирэмсний амралт хэдэн хоног вэ?" },
      { role: "assistant", content: "Жирэмсний амралт 120 хоног байна." },
    ]);
  });

  it("drops error-kind turns — UI-side connection failures, never something actually said", () => {
    const result = buildHistoryMessages([
      message("user", "асуулт нэг"),
      message("assistant", "Холболтын алдаа гарлаа. Дахин оролдоно уу.", { kind: "error" }),
      message("user", "асуулт хоёр"),
      message("assistant", "хариулт хоёр"),
    ]);

    expect(result.map((m) => m.content)).toEqual(["асуулт нэг", "асуулт хоёр", "хариулт хоёр"]);
  });

  it("keeps refusal turns — a refusal is still a real prior turn a followup can reference", () => {
    const result = buildHistoryMessages([
      message("user", "асуулт"),
      message("assistant", "Уучлаарай, олдсонгүй.", { kind: "refusal" }),
    ]);

    expect(result).toHaveLength(2);
  });

  it("caps at maxTurns exchanges, trimming the oldest first", () => {
    const messages = [];
    for (let i = 1; i <= 5; i++) {
      messages.push(message("user", `асуулт ${i}`));
      messages.push(message("assistant", `хариулт ${i}`));
    }

    // maxTurns: 2 exchanges = 4 messages, and none of these are anywhere
    // near the token budget, so the turn cap is the only thing trimming.
    const result = buildHistoryMessages(messages, { maxTurns: 2, maxTokens: 100000 });

    expect(result.map((m) => m.content)).toEqual([
      "асуулт 4",
      "хариулт 4",
      "асуулт 5",
      "хариулт 5",
    ]);
  });

  it("trims oldest-first under the token budget", () => {
    // Each message is ~50 chars -> ~13 estimated tokens. A budget of 20
    // tokens fits the newest message plus a sliver, not two.
    const longText = "x".repeat(50);
    const messages = [
      message("user", longText, { id: "oldest" }),
      message("assistant", longText, { id: "newest" }),
    ];

    const result = buildHistoryMessages(messages, { maxTurns: 6, maxTokens: 20 });

    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({ role: "assistant", content: longText });
  });

  it("always keeps the single most recent entry even if it alone exceeds the token budget", () => {
    // A detailed prior answer easily runs past a small budget on its own —
    // dropping it would send the very next followup with zero context.
    const longAnswer = "х".repeat(20000);
    const messages = [message("user", "асуулт"), message("assistant", longAnswer)];

    const result = buildHistoryMessages(messages, { maxTurns: 6, maxTokens: 100 });

    expect(result).toEqual([{ role: "assistant", content: longAnswer }]);
  });

  it("returns an empty array for a first turn with no prior messages", () => {
    expect(buildHistoryMessages([])).toEqual([]);
  });
});
