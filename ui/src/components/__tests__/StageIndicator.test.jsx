import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StageIndicator from "../StageIndicator.jsx";

describe("StageIndicator", () => {
  it("shows a short label while retrieving", () => {
    render(<StageIndicator stage="retrieving" />);
    expect(screen.getByText("Хайж байна…")).toBeInTheDocument();
  });

  it("shows the document count once retrieval returns", () => {
    render(<StageIndicator stage="retrieved" documentCount={5} />);
    expect(screen.getByText("5 баримт олдлоо")).toBeInTheDocument();
  });

  it("shows 0 rather than blank when retrieval found nothing", () => {
    render(<StageIndicator stage="retrieved" documentCount={0} />);
    expect(screen.getByText("0 баримт олдлоо")).toBeInTheDocument();
  });

  it("shows a short label while generating", () => {
    render(<StageIndicator stage="generating" />);
    expect(screen.getByText("Хариулт бэлтгэж байна…")).toBeInTheDocument();
  });

  it("defaults to the retrieving label for an unknown/missing stage", () => {
    render(<StageIndicator />);
    expect(screen.getByText("Хайж байна…")).toBeInTheDocument();
  });
});
