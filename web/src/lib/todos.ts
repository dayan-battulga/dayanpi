import type { NavigateFunction } from "react-router";
import { request } from "@/lib/http";
import type { Priority, TodoItem, Todos } from "@/lib/types";

export const TODO_TEXT_MAX = 200;
export const NEW_TODO_ID = "new-todo";

// Brings the new to-do box into view with the cursor in it; false when this page doesn't have one.
export function focusNewTodo(): boolean {
  const input = document.getElementById(NEW_TODO_ID);
  input?.scrollIntoView({ block: "center" });
  input?.focus({ preventScroll: true });
  return input != null;
}

// The dock's + and ⌘K's N. On the Desk the box is right there, and focusing it inside the tap is what opens a phone's
// keyboard; from another page the Desk focuses it once it's drawn (DeskPage reads state.addTodo).
export function openNewTodo(navigate: NavigateFunction): void {
  if (!focusNewTodo()) {
    void navigate("/me", { state: { addTodo: Date.now() } });
  }
}

export interface TodoChange {
  text?: string;
  done?: boolean;
  current?: boolean;
  priority?: Priority;
}

// focus/todos.py's PRIORITIES, in the notepad's order, with the chip's and the menu's words.
export const PRIORITIES: { value: Priority; label: string }[] = [
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
  { value: "none", label: "No priority" },
];
export const SHOW_EVERY_PRIORITY: Record<Priority, boolean> = { high: true, medium: true, low: true, none: true };
const PRIORITY_WORDS: Record<Priority, string> = { high: "high", medium: "medium", low: "low", none: "no" };

const readPriority = (item: TodoItem): Priority => item.priority ?? "none";

export interface NotepadList {
  current: TodoItem | null; // what you're working on, always first
  rows: TodoItem[];
}

// The Room's notepad: what you're working on, then your other open to-dos, high first and none last (each group in the
// list's own order). Only the priorities you show, plus the ones you just added from the notepad (kept).
export function listNotepad(todos: Todos, shown: Record<Priority, boolean>, kept: string[]): NotepadList {
  const rank = (item: TodoItem) => PRIORITIES.findIndex((entry) => entry.value === readPriority(item));
  const rows = todos.open
    .filter((item) => item.id !== todos.current && (shown[readPriority(item)] || kept.includes(item.id)))
    .sort((first, second) => rank(first) - rank(second));
  const listed = { current: todos.open.find((item) => item.id === todos.current) ?? null, rows };
  return listed;
}

// The notepad's header: "All to-dos", "High and medium priority", "No priority", "Only what you’re working on".
export function describeShown(shown: Record<Priority, boolean>): string {
  const words = PRIORITIES.filter((entry) => shown[entry.value]).map((entry) => PRIORITY_WORDS[entry.value]);
  const joined = words.length > 1 ? `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}` : words.join("");
  let text = `${joined.charAt(0).toUpperCase()}${joined.slice(1)} priority`;
  if (words.length === PRIORITIES.length) {
    text = "All to-dos";
  } else if (words.length === 0) {
    text = "Only what you’re working on";
  }
  return text;
}

// What the list will look like once the Pi takes a change, the way focus/todos.py does it: a checked item leaves
// the open list (and stops being current), an unchecked one goes back to the end of it, only an open item can be
// current. The Pi's reply puts an unchecked item back in its own place.
export function applyTodoChange(todos: Todos, id: string, change: TodoChange, now: number): Todos {
  const item = [...todos.open, ...todos.done].find((entry) => entry.id === id);
  let next = todos;
  if (item != null) {
    const doneAt = change.done === undefined ? item.done_at : change.done ? (item.done_at ?? now) : null;
    const edited = { ...item, text: change.text ?? item.text, done_at: doneAt, priority: change.priority ?? item.priority };
    const replaceIn = (list: TodoItem[]) => (list.some((entry) => entry.id === id) ? list.map((entry) => (entry.id === id ? edited : entry)) : [...list, edited]);
    const without = (list: TodoItem[]) => list.filter((entry) => entry.id !== id);
    let current = todos.current;
    if (doneAt != null && current === id) {
      current = null;
    } else if (change.current === true && doneAt == null) {
      current = id;
    } else if (change.current === false && current === id) {
      current = null;
    }
    next = { current, open: doneAt == null ? replaceIn(todos.open) : without(todos.open), done: doneAt == null ? without(todos.done) : replaceIn(todos.done) };
  }
  return next;
}

export function removeTodo(todos: Todos, id: string): Todos {
  const without = (list: TodoItem[]) => list.filter((entry) => entry.id !== id);
  const next = { current: todos.current === id ? null : todos.current, open: without(todos.open), done: without(todos.done) };
  return next;
}

// Sends one change and hands back the list the server replied with, or null if it didn't work.
export async function sendTodo(method: "POST" | "PATCH" | "DELETE", path: string, body?: object): Promise<Todos | null> {
  const reply = await request<{ todos: Todos }>(method, path, body);
  const todos = reply.body?.todos ?? null;
  return todos;
}
