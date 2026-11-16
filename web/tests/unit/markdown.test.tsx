import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Markdown } from "@/components/chat/Markdown";
import { parseInline, parseMarkdown } from "@/lib/markdown/parse";

describe("parseMarkdown", () => {
  it("splits paragraphs on blank lines and joins soft line breaks", () => {
    expect(parseMarkdown("First line\nsame paragraph.\n\nSecond.")).toEqual([
      { type: "paragraph", children: [{ type: "text", value: "First line same paragraph." }] },
      { type: "paragraph", children: [{ type: "text", value: "Second." }] },
    ]);
  });

  it("groups consecutive '- ' lines into one list", () => {
    const blocks = parseMarkdown("Intro:\n- one\n- **two**\n\nAfter");
    expect(blocks.map((b) => b.type)).toEqual(["paragraph", "list", "paragraph"]);
    const list = blocks[1];
    expect(list?.type === "list" && list.items).toHaveLength(2);
  });

  it("parses bold and citation markers, including grouped markers", () => {
    expect(parseInline("A **key** fact [1][2] and [3, 4].")).toEqual([
      { type: "text", value: "A " },
      { type: "strong", children: [{ type: "text", value: "key" }] },
      { type: "text", value: " fact " },
      { type: "cite", n: 1 },
      { type: "cite", n: 2 },
      { type: "text", value: " and " },
      { type: "cite", n: 3 },
      { type: "cite", n: 4 },
      { type: "text", value: "." },
    ]);
  });

  it("leaves an unmatched ** as literal text (mid-stream)", () => {
    expect(parseInline("Some **unfinished")).toEqual([{ type: "text", value: "Some **unfinished" }]);
  });

  it("treats Markdown links, images and headings as plain text", () => {
    expect(parseInline("[click](https://evil.example) ![x](y)")).toEqual([
      { type: "text", value: "[click](https://evil.example) ![x](y)" },
    ]);
    expect(parseMarkdown("# Title")).toEqual([{ type: "paragraph", children: [{ type: "text", value: "# Title" }] }]);
  });

  it("returns nothing for empty or whitespace input", () => {
    expect(parseMarkdown("  \n\n ")).toEqual([]);
  });
});

describe("<Markdown>", () => {
  const citations = new Map([[1, { n: 1, title: "Diabetes" }]]);

  it("renders citation buttons only for known citations", () => {
    const onCite = vi.fn();
    render(<Markdown text="Fact [1] and [9]." citations={citations} onCite={onCite} citeLabel={(n, t) => `Source ${n}: ${t}`} />);
    const button = screen.getByRole("button", { name: "Source 1: Diabetes" });
    fireEvent.click(button);
    expect(onCite).toHaveBeenCalledWith(1, button);
    expect(screen.getByText(/\[9\]/)).toBeTruthy();
    expect(screen.queryAllByRole("button")).toHaveLength(1);
  });

  it("renders XSS attempts as inert text", () => {
    const attack = [
      "<script>window.__pwned = 1</script>",
      '<img src=x onerror="window.__pwned=1">',
      "[link](javascript:alert(1))",
      "![img](https://evil.example/pixel.png)",
      '<a href="https://evil.example">x</a>',
      "**<iframe src=//evil.example>**",
    ].join("\n\n");
    const { container } = render(<Markdown text={attack} citations={new Map()} onCite={() => undefined} citeLabel={() => ""} />);
    expect(container.querySelector("script, img, a, iframe, [onerror], [href], [src]")).toBeNull();
    expect(container.textContent).toContain("<script>window.__pwned = 1</script>");
    expect(container.textContent).toContain("[link](javascript:alert(1))");
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  });

  it("renders lists and bold", () => {
    const { container } = render(<Markdown text={"- a **b**\n- c"} citations={new Map()} onCite={() => undefined} citeLabel={() => ""} />);
    expect(container.querySelectorAll("ul > li")).toHaveLength(2);
    expect(container.querySelector("strong")?.textContent).toBe("b");
  });
});
