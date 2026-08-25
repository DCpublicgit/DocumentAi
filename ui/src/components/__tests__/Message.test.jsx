import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Message from "../Message.jsx";

const citations = [
  {
    file: "L1-POL-10_МАБ-ын_сургалт_мэдээллийн_бодлого.txt",
    section: "Заалт 2.1: Text one",
    version: "v1",
    effectiveDate: "2025-11-05",
  },
];

describe("Message", () => {
  it("renders only the refusal text, never a citation panel — even if citations data is present", () => {
    const { container } = render(
      <Message
        message={{
          role: "assistant",
          kind: "refusal",
          text: "Уучлаарай, энэ асуултын хариулт манай компанийн бодлогод байхгүй байна.",
          streaming: false,
          // Defensive: a refusal must stay citation-free regardless of what
          // upstream state happens to be sitting in this field.
          citations,
        }}
      />,
    );

    expect(
      screen.getByText("Уучлаарай, энэ асуултын хариулт манай компанийн бодлогод байхгүй байна."),
    ).toBeInTheDocument();
    expect(container.querySelector(".citation-line")).not.toBeInTheDocument();
    expect(container.querySelector(".citation-row")).not.toBeInTheDocument();
  });

  it("renders a citation panel for a real (non-refusal) answer with citations", () => {
    const { container } = render(
      <Message
        message={{
          role: "assistant",
          kind: "answer",
          text: "Энэ бол жинхэнэ хариулт.",
          streaming: false,
          citations,
        }}
      />,
    );

    expect(container.querySelector(".citation-line")).toBeInTheDocument();
  });
});
