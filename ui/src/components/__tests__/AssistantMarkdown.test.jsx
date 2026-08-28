import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AssistantMarkdown from "../AssistantMarkdown.jsx";

describe("AssistantMarkdown", () => {
  it("renders bold section labels as <strong>", () => {
    const { container } = render(<AssistantMarkdown text="**Товч хариулт**" />);

    const strong = container.querySelector("strong");
    expect(strong).toBeInTheDocument();
    expect(strong).toHaveTextContent("Товч хариулт");
  });

  it("renders a '- ' bulleted section as a real list", () => {
    const { container } = render(
      <AssistantMarkdown text={"- Нэгдүгээр зүйл\n- Хоёрдугаар зүйл"} />,
    );

    const items = container.querySelectorAll("ul > li");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Нэгдүгээр зүйл");
    expect(items[1]).toHaveTextContent("Хоёрдугаар зүйл");
  });

  it("renders a GFM table wrapped in an overflow-x:auto container", () => {
    const text = "| A | B |\n| --- | --- |\n| 1 | 2 |";
    const { container } = render(<AssistantMarkdown text={text} />);

    const wrapper = container.querySelector(".assistant-table-scroll");
    expect(wrapper).toBeInTheDocument();
    const table = wrapper.querySelector("table");
    expect(table).toBeInTheDocument();
    expect(container.querySelectorAll("th")).toHaveLength(2);
    expect(container.querySelectorAll("td")).toHaveLength(2);
  });

  it("gives links target=_blank and rel=noopener noreferrer", () => {
    const { container } = render(<AssistantMarkdown text="[бодлого](https://example.com)" />);

    const link = container.querySelector("a");
    expect(link).toHaveAttribute("href", "https://example.com");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("strips a disallowed element (heading) down to its text, never an <h1>", () => {
    const { container } = render(<AssistantMarkdown text="# Гарчиг байж болохгүй" />);

    expect(container.querySelector("h1")).not.toBeInTheDocument();
    expect(screen.getByText(/Гарчиг байж болохгүй/)).toBeInTheDocument();
  });

  it("never executes or renders raw HTML — it shows as inert text, not a real element", () => {
    const { container } = render(
      <AssistantMarkdown text='энэ бол <img src=x onerror="window.__pwned = true"> текст' />,
    );

    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(window.__pwned).toBeUndefined();
  });

  it("never renders a real <script> tag from embedded raw HTML", () => {
    const { container } = render(
      <AssistantMarkdown text="текст <script>window.__pwned = true</script> дараа" />,
    );

    expect(container.querySelector("script")).not.toBeInTheDocument();
    expect(window.__pwned).toBeUndefined();
  });

  it("does not throw on a partial, mid-stream string with an unclosed bold marker", () => {
    expect(() => render(<AssistantMarkdown text="**Товч хари" />)).not.toThrow();
  });

  it("does not throw on a partial, mid-stream table with only a header row", () => {
    expect(() => render(<AssistantMarkdown text="| A | B |\n| --- |" />)).not.toThrow();
  });

  it("renders the two-section shape a real streamed answer produces", () => {
    const text =
      "**Товч хариулт**\n\nЖирэмсний амралт 120 хоног байна.\n\n**Дэлгэрэнгүй тайлбар**\n\n- Нэг.\n- Хоёр.";
    const { container } = render(<AssistantMarkdown text={text} />);

    const strongs = container.querySelectorAll("strong");
    expect(strongs).toHaveLength(2);
    expect(strongs[0]).toHaveTextContent("Товч хариулт");
    expect(strongs[1]).toHaveTextContent("Дэлгэрэнгүй тайлбар");
    expect(container.querySelectorAll("ul > li")).toHaveLength(2);
  });

  it("renders an inline '[N]' marker as a clickable citation button", () => {
    const { container } = render(
      <AssistantMarkdown text="Ажилтан бүр сургалтад хамрагдана.[1]" onOpenCitation={() => {}} />,
    );

    const marker = container.querySelector("button.citation-marker");
    expect(marker).toBeInTheDocument();
    expect(marker).toHaveTextContent("[1]");
  });

  it("calls onOpenCitation with the marker's index when clicked", () => {
    const onOpenCitation = vi.fn();
    const { container } = render(
      <AssistantMarkdown text="Заалт.[3]" onOpenCitation={onOpenCitation} />,
    );

    fireEvent.click(container.querySelector("button.citation-marker"));

    expect(onOpenCitation).toHaveBeenCalledWith(3);
  });

  it("renders multiple adjacent markers as separate buttons", () => {
    const { container } = render(
      <AssistantMarkdown text="Хоёр эх сурвалж.[1][2]" onOpenCitation={() => {}} />,
    );

    const markers = container.querySelectorAll("button.citation-marker");
    expect(markers).toHaveLength(2);
    expect(markers[0]).toHaveTextContent("[1]");
    expect(markers[1]).toHaveTextContent("[2]");
  });

  it("renders a '[N]' marker inside a bulleted list item, not just top-level text", () => {
    const { container } = render(
      <AssistantMarkdown text={"- Нэгдүгээр зүйл.[1]\n- Хоёрдугаар зүйл.[2]"} onOpenCitation={() => {}} />,
    );

    const items = container.querySelectorAll("li");
    expect(items[0].querySelector("button.citation-marker")).toHaveTextContent("[1]");
    expect(items[1].querySelector("button.citation-marker")).toHaveTextContent("[2]");
  });

  it("does not treat a bracketed non-number as a citation marker", () => {
    const { container } = render(
      <AssistantMarkdown text="Энгийн [тэмдэглэл] текст." onOpenCitation={() => {}} />,
    );

    expect(container.querySelector("button.citation-marker")).not.toBeInTheDocument();
    expect(screen.getByText(/\[тэмдэглэл\]/)).toBeInTheDocument();
  });
});
