import { useRef, useState } from "react";
import { showToast } from "@/components/ui/toaster";
import { applyTodoChange, removeTodo, sendTodo, type TodoChange } from "@/lib/todos";
import type { Todos } from "@/lib/types";

// A snapshot built just before a change can still arrive after the reply, so the reply wins for a moment.
const REPLY_HOLD_S = 2.5;
const NO_TODOS: Todos = { current: null, open: [], done: [] };

export interface TodoEditor {
  todos: Todos;
  addTodo: (text: string) => Promise<boolean>; // false when the Pi didn't take it
  changeTodo: (id: string, change: TodoChange) => void;
  deleteTodo: (id: string) => void;
}

// The list on screen: the stream's, except after a change. A change shows right away as a guess, then as the Pi's
// reply; a failed one goes back to the stream's list and says so. Only the newest request's answer counts, so an
// older reply can't undo a newer guess.
export function useTodos(streamed: Todos | undefined, now: number): TodoEditor {
  const [held, setHeld] = useState<{ todos: Todos; until: number } | null>(null);
  const newest = useRef(0);
  const todos = held != null && now < held.until ? held.todos : (streamed ?? NO_TODOS);

  const send = async (guess: Todos | null, method: "POST" | "PATCH" | "DELETE", path: string, body: object | undefined, failure: string) => {
    const ticket = ++newest.current;
    if (guess != null) {
      setHeld({ todos: guess, until: Infinity });
    }
    const replied = await sendTodo(method, path, body);
    if (ticket === newest.current) {
      setHeld(replied == null ? null : { todos: replied, until: Date.now() / 1000 + REPLY_HOLD_S });
    }
    if (replied == null) {
      showToast(failure);
    }
    return replied != null;
  };

  // A new row only shows once the Pi has given it an id, so nothing swaps keys under the rise.
  const addTodo = (text: string) => send(null, "POST", "/api/todos", { text }, "Couldn't add that to-do");
  const changeTodo = (id: string, change: TodoChange) => {
    void send(applyTodoChange(todos, id, change, now), "PATCH", `/api/todos/${id}`, change, "Couldn't save that change");
  };
  const deleteTodo = (id: string) => {
    void send(removeTodo(todos, id), "DELETE", `/api/todos/${id}`, undefined, "Couldn't delete that to-do");
  };
  return { todos, addTodo, changeTodo, deleteTodo };
}
