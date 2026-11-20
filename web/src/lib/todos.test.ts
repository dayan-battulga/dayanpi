import { expect, it } from "vitest";
import { applyTodoChange, describeShown, listNotepad, SHOW_EVERY_PRIORITY } from "@/lib/todos";
import type { Todos } from "@/lib/types";

const TODOS: Todos = {
  current: "a",
  open: [
    { id: "a", text: "Problem set", seconds: 60, done_at: null, priority: "low" },
    { id: "b", text: "Lab report", seconds: 0, done_at: null, priority: "medium" },
    { id: "c", text: "Old one", seconds: 0, done_at: null }, // saved before priorities: none
    { id: "d", text: "Demo", seconds: 0, done_at: null, priority: "high" },
    { id: "e", text: "Gift", seconds: 0, done_at: null, priority: "low" },
    { id: "f", text: "Email", seconds: 0, done_at: null, priority: "high" },
  ],
  done: [{ id: "g", text: "Done one", seconds: 0, done_at: 1, priority: "high" }],
};
const texts = (todos: Todos, shown = SHOW_EVERY_PRIORITY, kept: string[] = []) => listNotepad(todos, shown, kept).rows.map((item) => item.text);

it("lists what you're working on first, then the rest high to none, each group in the list's order", () => {
  expect(listNotepad(TODOS, SHOW_EVERY_PRIORITY, []).current?.text).toBe("Problem set");
  expect(texts(TODOS)).toEqual(["Demo", "Email", "Lab report", "Gift", "Old one"]);
});

it("shows only the picked priorities, but always what you're working on and what you just added", () => {
  const shown = { high: true, medium: false, low: false, none: false };
  expect(texts(TODOS, shown)).toEqual(["Demo", "Email"]);
  expect(listNotepad(TODOS, shown, []).current?.text).toBe("Problem set"); // low, and still first
  expect(texts(TODOS, shown, ["c"])).toEqual(["Demo", "Email", "Old one"]);
  expect(listNotepad({ ...TODOS, current: null }, shown, []).current).toBeNull();
});

it("says which priorities the notepad shows", () => {
  expect(describeShown(SHOW_EVERY_PRIORITY)).toBe("All to-dos");
  expect(describeShown({ high: true, medium: true, low: false, none: false })).toBe("High and medium priority");
  expect(describeShown({ high: true, medium: false, low: true, none: true })).toBe("High, low and no priority");
  expect(describeShown({ high: false, medium: false, low: false, none: true })).toBe("No priority");
  expect(describeShown({ high: false, medium: false, low: false, none: false })).toBe("Only what you’re working on");
});

it("guesses a priority change right away", () => {
  expect(applyTodoChange(TODOS, "c", { priority: "high" }, 0).open.find((item) => item.id === "c")?.priority).toBe("high");
  expect(applyTodoChange(TODOS, "d", { text: "Demo day" }, 0).open.find((item) => item.id === "d")?.priority).toBe("high");
});
