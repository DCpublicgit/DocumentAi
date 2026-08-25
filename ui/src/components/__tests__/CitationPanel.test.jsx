import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CitationPanel from "../CitationPanel.jsx";

const citations = [
  {
    file: "L1-POL-10_МАБ-ын_сургалт_мэдээллийн_бодлого.txt",
    section: "Заалт 2.1: Text one",
    version: "v1",
    effectiveDate: "2025-11-05",
  },
  {
    file: "L1-POL-10_МАБ-ын_сургалт_мэдээллийн_бодлого.txt",
    section: "Заалт 4.1: Text two",
    version: "v1",
    effectiveDate: "2025-11-05",
  },
  {
    file: "L1-POL-10_МАБ-ын_сургалт_мэдээллийн_бодлого.txt",
    section: "Заалт 3.1: Text three",
    version: "v1",
    effectiveDate: "2025-11-05",
  },
  {
    file: "Чөлөө олгох журам.pdf",
    section: "1.2",
    version: "v3",
    effectiveDate: "2025-01-01",
  },
];

describe("CitationPanel", () => {
  it("renders one flat plain-text line per file", () => {
    const { container } = render(<CitationPanel citations={citations} />);

    const lines = container.querySelectorAll(".citation-line");
    expect(lines).toHaveLength(2);
  });

  it("groups multiple clauses from the same file onto one line, numerically sorted", () => {
    render(<CitationPanel citations={citations} />);

    expect(
      screen.getByText(
        "L1-POL-10_МАБ-ын_сургалт_мэдээллийн_бодлого.txt (Заалт 2.1, 3.1, 4.1)",
      ),
    ).toBeInTheDocument();
  });

  it("renders a file with no clause number as just the file name, no parens", () => {
    render(<CitationPanel citations={citations} />);

    expect(screen.getByText("Чөлөө олгох журам.pdf")).toBeInTheDocument();
    expect(screen.queryByText(/Чөлөө олгох журам\.pdf \(/)).not.toBeInTheDocument();
  });

  it("has no card/expand affordance: no buttons, no dl, no icons", () => {
    const { container } = render(<CitationPanel citations={citations} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(container.querySelector("dl")).not.toBeInTheDocument();
    expect(container.querySelector("svg")).not.toBeInTheDocument();
  });

  it("does not render policy_version or effective_date", () => {
    render(<CitationPanel citations={citations} />);

    expect(screen.queryByText(/v1/)).not.toBeInTheDocument();
    expect(screen.queryByText(/2025-11-05/)).not.toBeInTheDocument();
  });
});
