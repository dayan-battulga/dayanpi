import { request } from "@/lib/http";
import type { Todos } from "@/lib/types";

export const TODO_TEXT_MAX = 200;

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
