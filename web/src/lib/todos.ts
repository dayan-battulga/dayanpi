import type { NavigateFunction } from "react-router";
import { request } from "@/lib/http";
import type { Todos } from "@/lib/types";

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

// Sends one change and hands back the list the server replied with, or null if it didn't work.
export async function sendTodo(method: "POST" | "PATCH" | "DELETE", path: string, body?: object): Promise<Todos | null> {
  const reply = await request<{ todos: Todos }>(method, path, body);
  const todos = reply.body?.todos ?? null;
  return todos;
}
