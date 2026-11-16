export type PageBlock =
  | { kind: "heading"; level: 1 | 2; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "paragraph"; text: string };

// Reads the markdown the day pages are written in: the frontmatter (skipped), # and ##
// headings, "- " lists and plain lines. Anything else comes through as plain text, so a
// page edited in Obsidian still reads fine. Text only, never HTML.
export function parseDayPage(markdown: string): PageBlock[] {
  const lines = markdown.split("\n");
  const frontmatterEnd = lines[0] === "---" ? lines.indexOf("---", 1) : -1;
  const blocks: PageBlock[] = [];
  for (const line of lines.slice(frontmatterEnd + 1)) {
    const text = line.trim();
    const last = blocks[blocks.length - 1];
    if (text.startsWith("## ")) {
      blocks.push({ kind: "heading", level: 2, text: text.slice(3) });
    } else if (text.startsWith("# ")) {
      blocks.push({ kind: "heading", level: 1, text: text.slice(2) });
    } else if (text.startsWith("- ") && last?.kind === "list") {
      last.items.push(text.slice(2));
    } else if (text.startsWith("- ")) {
      blocks.push({ kind: "list", items: [text.slice(2)] });
    } else if (text !== "") {
      blocks.push({ kind: "paragraph", text });
    }
  }
  return blocks;
}
