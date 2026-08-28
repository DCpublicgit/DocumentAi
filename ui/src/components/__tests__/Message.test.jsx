import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
  it("spins the avatar icon for the whole turn while the answer is streaming", () => {
    const { container } = render(
      <Message
        message={{
          role: "assistant",
          kind: "answer",
          text: "Хэсэгчилсэн хариулт",
          streaming: true,
          citations: [],
        }}
      />,
    );

    expect(container.querySelector(".avatar")).toHaveClass("avatar--spin");
  });

  it("stops spinning the avatar once the answer finishes", () => {
    const { container } = render(
      <Message
        message={{
          role: "assistant",
          kind: "answer",
          text: "Бүрэн хариулт",
          streaming: false,
          citations: [],
        }}
      />,
    );

    expect(container.querySelector(".avatar")).not.toHaveClass("avatar--spin");
  });

  it("shows the stage indicator, not the answer body, while waiting for the first token", () => {
    const { container } = render(
      <Message
        message={{
          role: "assistant",
          kind: "answer",
          text: "",
          streaming: true,
          citations: [],
          stage: "retrieved",
          stageDocumentCount: 4,
        }}
      />,
    );

    expect(screen.getByText("4 баримт олдлоо")).toBeInTheDocument();
    expect(container.querySelector(".assistant-text")).not.toBeInTheDocument();
  });

  it("swaps the stage indicator out for the real answer once text starts arriving", () => {
    const { container } = render(
      <Message
        message={{
          role: "assistant",
          kind: "answer",
          text: "Эхлэл",
          streaming: true,
          citations: [],
          stage: "generating",
        }}
      />,
    );

    expect(screen.queryByText("Хариулт бэлтгэж байна…")).not.toBeInTheDocument();
    expect(container.querySelector(".stage-indicator")).not.toBeInTheDocument();
    expect(screen.getByText("Эхлэл")).toBeInTheDocument();
  });

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

  it("shows a retry button for a failed send and calls onRetry with the message id", () => {
    const onRetry = vi.fn();
    render(
      <Message
        message={{
          id: "m1",
          role: "assistant",
          kind: "error",
          text: "Интернэт холболт тасарсан байна. Холболтоо шалгаад дахин оролдоно уу.",
          streaming: false,
          citations: [],
          retryPayload: { question: "Асуулт", history: [] },
        }}
        conversationId="c1"
        onRetry={onRetry}
      />,
    );

    const button = screen.getByText("Дахин оролдох");
    fireEvent.click(button);

    expect(onRetry).toHaveBeenCalledWith("m1");
  });

  it("shows no retry button for an error message with no retryPayload", () => {
    render(
      <Message
        message={{
          id: "m1",
          role: "assistant",
          kind: "error",
          text: "Холболтын алдаа гарлаа. Дахин оролдоно уу.",
          streaming: false,
          citations: [],
        }}
        conversationId="c1"
      />,
    );

    expect(screen.queryByText("Дахин оролдох")).not.toBeInTheDocument();
  });

  it("disables the retry button while retryDisabled is true", () => {
    render(
      <Message
        message={{
          id: "m1",
          role: "assistant",
          kind: "error",
          text: "Серверийн алдаа гарлаа. Түр хүлээгээд дахин оролдоно уу.",
          streaming: false,
          citations: [],
          retryPayload: { question: "Асуулт", history: [] },
        }}
        conversationId="c1"
        onRetry={vi.fn()}
        retryDisabled
      />,
    );

    expect(screen.getByText("Дахин оролдох")).toBeDisabled();
  });

  describe("visually-hidden speaker labels", () => {
    it("labels a user bubble for screen readers, without changing the visible text", () => {
      render(
        <Message
          message={{ role: "user", text: "Ажлын цаг хэд вэ?", kind: "answer", citations: [] }}
        />,
      );

      expect(screen.getByText("Ажлын цаг хэд вэ?")).toBeInTheDocument();
      const label = screen.getByText("Таны асуулт:", { exact: false });
      expect(label).toHaveClass("sr-only");
    });

    it("labels a normal answer bubble for screen readers", () => {
      render(
        <Message
          message={{
            role: "assistant",
            kind: "answer",
            text: "Энэ бол хариулт.",
            streaming: false,
            citations: [],
          }}
        />,
      );

      expect(screen.getByText("Туслахын хариулт:", { exact: false })).toHaveClass("sr-only");
    });

    it("labels a refusal bubble for screen readers too, not just a real answer", () => {
      render(
        <Message
          message={{
            role: "assistant",
            kind: "refusal",
            text: "Уучлаарай, олдсонгүй.",
            streaming: false,
            citations: [],
          }}
        />,
      );

      expect(screen.getByText("Туслахын хариулт:", { exact: false })).toHaveClass("sr-only");
    });

    it("labels an error bubble for screen readers too", () => {
      render(
        <Message
          message={{
            id: "m1",
            role: "assistant",
            kind: "error",
            text: "Холболтын алдаа гарлаа. Дахин оролдоно уу.",
            streaming: false,
            citations: [],
          }}
          conversationId="c1"
        />,
      );

      expect(screen.getByText("Туслахын хариулт:", { exact: false })).toHaveClass("sr-only");
    });
  });
});
