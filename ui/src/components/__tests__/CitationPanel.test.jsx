import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import CitationPanel from "../CitationPanel.jsx";

const citations = [
  {
    index: 1,
    docId: "L1-POL-10_МАБ-ын_сургалт_мэдээллийн_бодлого.txt",
    title: "МАБ-ын сургалт мэдээллийн бодлого",
    clause: "2.1",
    snippet: "Text one",
    charStart: 0,
    charEnd: 8,
  },
  {
    index: 2,
    docId: "Чөлөө олгох журам.pdf",
    title: "Чөлөө олгох журам",
    clause: null,
    snippet: "Full chunk text",
    charStart: null,
    charEnd: null,
  },
];

describe("CitationPanel", () => {
  it("renders one clickable button per citation", () => {
    render(<CitationPanel citations={citations} onOpenCitation={() => {}} />);

    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);
  });

  it("shows the index, title, and clause when present", () => {
    render(<CitationPanel citations={citations} onOpenCitation={() => {}} />);

    expect(
      screen.getByText((text) => text.includes("МАБ-ын сургалт мэдээллийн бодлого")),
    ).toBeInTheDocument();
    expect(screen.getByText(/\(Заалт 2\.1\)/)).toBeInTheDocument();
  });

  it("shows just the title, no clause parenthetical, when clause is null", () => {
    render(<CitationPanel citations={citations} onOpenCitation={() => {}} />);

    expect(screen.queryByText(/Чөлөө олгох журам \(/)).not.toBeInTheDocument();
  });

  it("calls onOpenCitation with the full citation object when clicked", () => {
    const onOpenCitation = vi.fn();
    render(<CitationPanel citations={citations} onOpenCitation={onOpenCitation} />);

    fireEvent.click(screen.getAllByRole("button")[1]);

    expect(onOpenCitation).toHaveBeenCalledWith(citations[1]);
  });
});
