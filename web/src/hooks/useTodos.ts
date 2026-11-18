import { useHeldReply } from "@/hooks/useHeldReply";
import { applyTodoChange, removeTodo, sendTodo, type TodoChange } from "@/lib/todos";
import type { Todos } from "@/lib/types";

const NO_TODOS: Todos = { current: null, open: [], done: [] };

export interface TodoEditor {
  todos: Todos;
  addTodo: (text: string) => Promise<boolean>; // false when the Pi didn't take it
  changeTodo: (id: string, change: TodoChange) => void;
  deleteTodo: (id: string) => void;
}

// The list on screen: the stream's, except after a change, which shows right away as a guess, then as the Pi's reply
// (hooks/useHeldReply).
export function useTodos(streamed: Todos | undefined, now: number): TodoEditor {
  const { shown: todos, send } = useHeldReply(streamed ?? NO_TODOS, now);

  const sendChange = async (guess: Todos | null, method: "POST" | "PATCH" | "DELETE", path: string, body: object | undefined, failure: string) => {
    const replied = await send(guess, () => sendTodo(method, path, body), failure);
    return replied != null;
  };

  // A new row only shows once the Pi has given it an id, so nothing swaps keys under the rise.
  const addTodo = (text: string) => sendChange(null, "POST", "/api/todos", { text }, "Couldn't add that to-do");
  const changeTodo = (id: string, change: TodoChange) => {
    void sendChange(applyTodoChange(todos, id, change, now), "PATCH", `/api/todos/${id}`, change, "Couldn't save that change");
  };
  const deleteTodo = (id: string) => {
    void sendChange(removeTodo(todos, id), "DELETE", `/api/todos/${id}`, undefined, "Couldn't delete that to-do");
  };
  return { todos, addTodo, changeTodo, deleteTodo };
}
