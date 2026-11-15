import type { Todos } from "@/lib/types";

export const TODO_TEXT_MAX = 200;

export interface TodoChange {
  text?: string;
  done?: boolean;
  current?: boolean;
}

// Sends one change and hands back the list the server replied with, or null if it didn't work.
export async function sendTodo(method: "POST" | "PATCH" | "DELETE", path: string, body?: object): Promise<Todos | null> {
  let todos: Todos | null = null;
  try {
    const response = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body == null ? undefined : JSON.stringify(body),
    });
    todos = response.ok ? (await response.json()).todos : null;
  } catch {
    todos = null;
  }
  return todos;
}
