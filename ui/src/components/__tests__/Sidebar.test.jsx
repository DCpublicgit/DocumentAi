import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Sidebar from "../Sidebar.jsx";

const NOW = Date.now();

function conversation(id, title, overrides = {}) {
  return {
    id,
    title,
    createdAt: NOW,
    updatedAt: NOW,
    messages: [{ id: `${id}-1`, role: "user", text: "асуулт", kind: "answer", citations: [] }],
    ...overrides,
  };
}

function renderSidebar(props = {}) {
  const handlers = {
    onClose: vi.fn(),
    onNewChat: vi.fn(),
    onOpenConversation: vi.fn(),
    onRenameConversation: vi.fn(),
    onDeleteConversation: vi.fn(),
  };
  render(
    <Sidebar
      conversations={[]}
      activeId={null}
      isOpen
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe("Sidebar", () => {
  it("teaches the empty state instead of showing a bare list", () => {
    renderSidebar();
    expect(screen.getByText(/Хадгалсан яриа алга/)).toBeInTheDocument();
    // Nothing to search yet, so the field would be dead weight.
    expect(screen.queryByLabelText("Түүхээс хайх")).not.toBeInTheDocument();
  });

  it("lists conversations under a recency heading", () => {
    renderSidebar({ conversations: [conversation("a", "Цалингийн бодлого")] });

    expect(screen.getByRole("heading", { name: "Өнөөдөр" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Цалингийн бодлого" })).toBeInTheDocument();
  });

  it("marks the open conversation as current", () => {
    renderSidebar({
      conversations: [conversation("a", "Цалин"), conversation("b", "Чөлөө")],
      activeId: "b",
    });

    expect(screen.getByRole("button", { name: "Чөлөө" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "Цалин" })).not.toHaveAttribute("aria-current");
  });

  it("opens the conversation that was clicked", async () => {
    const user = userEvent.setup();
    const handlers = renderSidebar({ conversations: [conversation("a", "Цалин")] });

    await user.click(screen.getByRole("button", { name: "Цалин" }));
    expect(handlers.onOpenConversation).toHaveBeenCalledWith("a");
  });

  it("filters the list and explains an empty search result", async () => {
    const user = userEvent.setup();
    renderSidebar({
      conversations: [conversation("a", "Цалингийн бодлого"), conversation("b", "Чөлөөний журам")],
    });

    await user.type(screen.getByLabelText("Түүхээс хайх"), "чөлөө");
    expect(screen.getByRole("button", { name: "Чөлөөний журам" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Цалингийн бодлого" })).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText("Түүхээс хайх"));
    await user.type(screen.getByLabelText("Түүхээс хайх"), "тэтгэвэр");
    expect(screen.getByText(/олдсонгүй/)).toBeInTheDocument();
  });

  it("renames a conversation from the row menu", async () => {
    const user = userEvent.setup();
    const handlers = renderSidebar({ conversations: [conversation("a", "Цалин")] });

    await user.click(screen.getByRole("button", { name: /үйлдлүүд/ }));
    await user.click(screen.getByRole("menuitem", { name: "Нэр өөрчлөх" }));

    const input = screen.getByLabelText("Ярианы нэр");
    await user.clear(input);
    await user.type(input, "Цалингийн асуулт{Enter}");

    expect(handlers.onRenameConversation).toHaveBeenCalledWith("a", "Цалингийн асуулт");
  });

  it("requires a confirm step before deleting", async () => {
    const user = userEvent.setup();
    const handlers = renderSidebar({ conversations: [conversation("a", "Цалин")] });

    await user.click(screen.getByRole("button", { name: /үйлдлүүд/ }));
    await user.click(screen.getByRole("menuitem", { name: "Устгах" }));
    expect(handlers.onDeleteConversation).not.toHaveBeenCalled();

    expect(screen.getByText("Энэ яриаг устгах уу?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Устгах" }));
    expect(handlers.onDeleteConversation).toHaveBeenCalledWith("a");
  });

  it("closes the row menu on Escape", async () => {
    const user = userEvent.setup();
    renderSidebar({ conversations: [conversation("a", "Цалин")] });

    await user.click(screen.getByRole("button", { name: /үйлдлүүд/ }));
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
