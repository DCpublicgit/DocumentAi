import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import CitationDrawer from "../CitationDrawer.jsx";

const citation = {
  index: 1,
  docId: "L1-POL-04_Бодлого.txt",
  title: "Мэдээллийн Аюулгүй Байдлын Бодлого",
  clause: "4.2",
  snippet: "4.1. Сүлжээ. 4.2. VPN ашиглалтын шаардлага. 4.3. Бусад.",
  charStart: 13,
  charEnd: 43,
};

describe("CitationDrawer", () => {
  it("renders the title, clause, and a link to the full document", () => {
    render(<CitationDrawer citation={citation} onClose={() => {}} />);

    expect(screen.getByText(citation.title)).toBeInTheDocument();
    expect(screen.getByText(/Заалт 4\.2/)).toBeInTheDocument();
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", `/v1/documents/${encodeURIComponent(citation.docId)}`);
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("highlights exactly the charStart:charEnd range with <mark>", () => {
    const { container } = render(<CitationDrawer citation={citation} onClose={() => {}} />);

    const mark = container.querySelector("mark");
    expect(mark).toHaveTextContent("VPN ашиглалтын шаардлага.");
  });

  it("shows the whole snippet with no <mark> when there is no highlight range", () => {
    const noHighlight = { ...citation, charStart: null, charEnd: null };
    const { container } = render(<CitationDrawer citation={noHighlight} onClose={() => {}} />);

    expect(container.querySelector("mark")).not.toBeInTheDocument();
    expect(screen.getByText(citation.snippet)).toBeInTheDocument();
  });

  it("moves focus to the close button when it opens", () => {
    render(<CitationDrawer citation={citation} onClose={() => {}} />);

    expect(screen.getByRole("button", { name: "Хаах" })).toHaveFocus();
  });

  it("calls onClose when Escape is pressed", () => {
    const onClose = vi.fn();
    render(<CitationDrawer citation={citation} onClose={onClose} />);

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when the close button or the scrim is clicked", () => {
    const onClose = vi.fn();
    const { container } = render(<CitationDrawer citation={citation} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Хаах" }));
    fireEvent.click(container.querySelector(".citation-drawer__scrim"));

    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("returns focus to whatever triggered it once it unmounts", () => {
    const trigger = document.createElement("button");
    trigger.textContent = "trigger";
    document.body.appendChild(trigger);
    trigger.focus();
    expect(trigger).toHaveFocus();

    const { unmount } = render(<CitationDrawer citation={citation} onClose={() => {}} />);
    expect(trigger).not.toHaveFocus(); // focus moved into the drawer on open

    unmount();

    expect(trigger).toHaveFocus();
    document.body.removeChild(trigger);
  });

  it("stops listening for Escape once unmounted", () => {
    const onClose = vi.fn();
    const { unmount } = render(<CitationDrawer citation={citation} onClose={onClose} />);
    unmount();

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onClose).not.toHaveBeenCalled();
  });

  it("renders nothing when citation is null", () => {
    const { container } = render(<CitationDrawer citation={null} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });
});
