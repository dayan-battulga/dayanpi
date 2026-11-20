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

export interface NamedTime {
  name: string;
  time: string; // "" when the line had none
}

export interface AppTime extends NamedTime {
  seconds: number;
  youtubeSeconds: number; // a browser's YouTube part, 0 on pages from before it was written down
}

export interface DayGoal {
  minutes: number;
  focusMinutes: number;
}

export interface DayPageParts {
  totals: NamedTime[]; // "Focus" → "4h 10m", and the rest of the Totals list
  todos: NamedTime[]; // the to-dos done, with their time
  apps: AppTime[]; // most first, as the page lists them
  goal: DayGoal | null; // the day's focus goal, from the frontmatter; none on days without one
  notes: string[]; // plain lines, like "Nothing was logged on this day." or how long Mac tracking was paused
}

// The page's own durations, "1h05", "12m" or "45s", in seconds; anything else is 0.
function readSeconds(time: string): number {
  const match = /^(?:(\d+)h(\d\d)|(\d+)m|(\d+)s)$/.exec(time);
  const seconds = match == null ? 0 : Number(match[1] ?? 0) * 3600 + Number(match[2] ?? match[3] ?? 0) * 60 + Number(match[4] ?? 0);
  return seconds;
}

// "Google Chrome: 1h41 (YouTube 22m)", or just "Code: 2h05".
function readApp(item: string): AppTime {
  const match = /^(.*): (\S+)(?: \(YouTube (\S+)\))?$/.exec(item);
  const time = match?.[2] ?? "";
  const app = { name: match?.[1] ?? item, time: spellTime(time), seconds: readSeconds(time), youtubeSeconds: readSeconds(match?.[3] ?? "") };
  return app;
}

// The whole numbers between the first two --- lines, like focus_minutes: 250.
function readNumbers(markdown: string): Map<string, number> {
  const lines = markdown.split("\n");
  const end = lines[0] === "---" ? lines.indexOf("---", 1) : -1;
  const numbers = new Map(
    lines
      .slice(1, Math.max(end, 1))
      .map((line) => /^(\w+): (\d+)$/.exec(line))
      .filter((match) => match != null)
      .map((match) => [match[1], Number(match[2])]),
  );
  return numbers;
}

// The page writes "1h05"; the dialog says "1h 05m" like the rest of the desk.
function spellTime(time: string): string {
  const spelled = time.replace(/^(\d+)h(\d\d)$/, "$1h $2m");
  return spelled;
}

// "Problem set 2 (1h40)" or "Focus: 1h40". The parentheses win, since a to-do's own text can have a colon.
function splitItem(item: string): NamedTime {
  const inParens = /^(.*) \(([^()]*)\)$/.exec(item);
  const colon = item.lastIndexOf(": ");
  const named = inParens ? { name: inParens[1], time: inParens[2] } : colon > 0 ? { name: item.slice(0, colon), time: item.slice(colon + 2) } : { name: item, time: "" };
  return { name: named.name, time: spellTime(named.time) };
}

// A day page (focus/days.py's build_day_page) in the pieces the day dialog lays out. A section's "- None" is no items.
export function readDayPage(markdown: string): DayPageParts {
  const numbers = readNumbers(markdown);
  const goal = numbers.get("goal_minutes");
  const parts: DayPageParts = { totals: [], todos: [], apps: [], goal: goal == null ? null : { minutes: goal, focusMinutes: numbers.get("focus_minutes") ?? 0 }, notes: [] };
  const lists = new Map([
    ["Totals", parts.totals],
    ["To-dos done", parts.todos],
  ]);
  let section = "";
  for (const block of parseDayPage(markdown)) {
    if (block.kind === "heading") {
      section = block.text;
    } else if (block.kind === "paragraph") {
      parts.notes.push(block.text);
    } else if (section === "Apps") {
      parts.apps.push(...block.items.filter((item) => item !== "None").map(readApp));
    } else {
      lists.get(section)?.push(...block.items.filter((item) => item !== "None").map(splitItem));
    }
  }
  return parts;
}
