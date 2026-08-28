import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MessageList from "../MessageList.jsx";

function message(id, role, text) {
  return { id, role, text, kind: "answer", citations: [], streaming: false };
}

// jsdom's default scroll metrics are all 0, and 0 - 0 - 0 <= 120 reads as
// "near bottom" — true unless a test overrides them, which is convenient
// for the near-bottom cases and made explicit here for the ones that must
// NOT be near the bottom.
function setNotNearBottom(el) {
  Object.defineProperty(el, "scrollTop", { value: 0, configurable: true });
  Object.defineProperty(el, "scrollHeight", { value: 1000, configurable: true });
  Object.defineProperty(el, "clientHeight", { value: 100, configurable: true });
}

let reducedMotion;

beforeEach(() => {
  reducedMotion = false;
  Element.prototype.scrollIntoView = vi.fn();
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: reducedMotion }));
});

describe("MessageList scroll management", () => {
  it("auto-scrolls smoothly on a new message when already near the bottom", () => {
    const { container, rerender } = render(
      <MessageList messages={[message("1", "user", "асуулт")]} conversationId="c1" />,
    );
    Element.prototype.scrollIntoView.mockClear();

    rerender(
      <MessageList
        messages={[message("1", "user", "асуулт"), message("2", "assistant", "хариулт")]}
        conversationId="c1"
      />,
    );

    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "smooth" }),
    );
    expect(container.querySelector(".jump-to-bottom")).not.toBeInTheDocument();
  });

  it("does not move the view, and shows the pill instead, when scrolled away from the bottom", () => {
    const { container, rerender } = render(
      <MessageList messages={[message("1", "user", "асуулт")]} conversationId="c1" />,
    );
    const list = container.querySelector(".message-list");
    setNotNearBottom(list);
    fireEvent.scroll(list);
    Element.prototype.scrollIntoView.mockClear();

    rerender(
      <MessageList
        messages={[message("1", "user", "асуулт"), message("2", "assistant", "хариулт")]}
        conversationId="c1"
      />,
    );

    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
    expect(screen.getByText("↓ шинэ хариулт")).toBeInTheDocument();
  });

  it("streamed token updates (same message count) scroll instantly, not smoothly", () => {
    const { rerender } = render(
      <MessageList
        messages={[message("1", "user", "асуулт"), message("2", "assistant", "Тов")]}
        conversationId="c1"
      />,
    );
    Element.prototype.scrollIntoView.mockClear();

    rerender(
      <MessageList
        messages={[message("1", "user", "асуулт"), message("2", "assistant", "Товч хариулт")]}
        conversationId="c1"
      />,
    );

    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "auto" }),
    );
  });

  it("respects prefers-reduced-motion: a new message scrolls instantly, not smoothly", () => {
    reducedMotion = true;
    const { rerender } = render(
      <MessageList messages={[message("1", "user", "асуулт")]} conversationId="c1" />,
    );
    Element.prototype.scrollIntoView.mockClear();

    rerender(
      <MessageList
        messages={[message("1", "user", "асуулт"), message("2", "assistant", "хариулт")]}
        conversationId="c1"
      />,
    );

    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "auto" }),
    );
  });

  it("clicking the jump pill scrolls to the bottom and dismisses itself", () => {
    const { container, rerender } = render(
      <MessageList messages={[message("1", "user", "асуулт")]} conversationId="c1" />,
    );
    const list = container.querySelector(".message-list");
    setNotNearBottom(list);
    fireEvent.scroll(list);
    rerender(
      <MessageList
        messages={[message("1", "user", "асуулт"), message("2", "assistant", "хариулт")]}
        conversationId="c1"
      />,
    );
    Element.prototype.scrollIntoView.mockClear();

    fireEvent.click(screen.getByText("↓ шинэ хариулт"));

    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "smooth" }),
    );
    expect(screen.queryByText("↓ шинэ хариулт")).not.toBeInTheDocument();
  });

  it("switching conversations jumps to the bottom instantly, even mid-scrollback, and clears the pill", () => {
    const { container, rerender } = render(
      <MessageList messages={[message("1", "user", "асуулт нэг")]} conversationId="c1" />,
    );
    const list = container.querySelector(".message-list");
    setNotNearBottom(list);
    fireEvent.scroll(list);
    Element.prototype.scrollIntoView.mockClear();

    rerender(
      <MessageList
        messages={[message("2", "user", "асуулт хоёр"), message("3", "assistant", "хариулт хоёр")]}
        conversationId="c2"
      />,
    );

    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "auto" }),
    );
    expect(screen.queryByText("↓ шинэ хариулт")).not.toBeInTheDocument();
  });
});

describe("MessageList accessibility", () => {
  it("announces the conversation as a polite live log, including additions and streamed text", () => {
    const { container } = render(
      <MessageList messages={[message("1", "user", "асуулт")]} conversationId="c1" />,
    );

    const log = container.querySelector(".message-list");
    expect(log).toHaveAttribute("role", "log");
    expect(log).toHaveAttribute("aria-live", "polite");
    expect(log).toHaveAttribute("aria-relevant", "additions text");
  });
});
