import type { NavigateFunction } from "react-router";
import { request } from "@/lib/http";
import type { TodoItem, Todos } from "@/lib/types";

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
}

// What the list will look like once the Pi takes a change, the way focus/todos.py does it: a checked item leaves
// the open list (and stops being current), an unchecked one goes back to the end of it, only an open item can be
// current. The Pi's reply puts an unchecked item back in its own place.
export function applyTodoChange(todos: Todos, id: string, change: TodoChange, now: number): Todos {
  const item = [...todos.open, ...todos.done].find((entry) => entry.id === id);
  let next = todos;
  if (item != null) {
    const doneAt = change.done === undefined ? item.done_at : change.done ? (item.done_at ?? now) : null;
    const edited = { ...item, text: change.text ?? item.text, done_at: doneAt };
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
