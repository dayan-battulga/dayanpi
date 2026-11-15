import { useState, type FormEvent } from "react";
import { riseDelay } from "@/components/shared/rise";
import { TodayList } from "@/components/todo/TodayList";
import { TodoRow } from "@/components/todo/TodoRow";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { TODO_TEXT_MAX, sendTodo, type TodoChange } from "@/lib/todos";
import type { Segment, Todos } from "@/lib/types";

// A snapshot built just before a change can still arrive after the reply, so the reply wins for a moment.
const REPLY_HOLD_S = 2.5;
const NO_TODOS: Todos = { current: null, open: [], done: [] };

interface TodoCardProps {
  todos: Todos | undefined;
  known: Segment[];
  now: number;
}

export function TodoCard({ todos, known, now }: TodoCardProps) {
  const [newText, setNewText] = useState("");
  const [reply, setReply] = useState<{ todos: Todos; until: number } | null>(null);
  const shown = reply != null && now < reply.until ? reply.todos : (todos ?? NO_TODOS);

  const send = async (method: "POST" | "PATCH" | "DELETE", path: string, body?: object) => {
    const replied = await sendTodo(method, path, body);
    if (replied != null) {
      setReply({ todos: replied, until: Date.now() / 1000 + REPLY_HOLD_S });
    }
  };
  const addTodo = (event: FormEvent) => {
    event.preventDefault();
    const text = newText.trim();
    if (text !== "") {
      setNewText("");
      send("POST", "/api/todos", { text });
    }
  };
  const changeTodo = (id: string, change: TodoChange) => send("PATCH", `/api/todos/${id}`, change);
  const deleteTodo = (id: string) => send("DELETE", `/api/todos/${id}`);

  return (
    <Card className="card todo rise gap-0" style={riseDelay(3)} aria-label="To-do and today">
      <div className="card-head">
        <div className="card-title">
          <h2 className="label">To-do</h2>
          <span className="mono muted small">{shown.open.length > 0 ? `${shown.open.length} open` : ""}</span>
        </div>
      </div>
      <form className="flex gap-2" onSubmit={addTodo}>
        <Input
          value={newText}
          onChange={(event) => setNewText(event.target.value)}
          maxLength={TODO_TEXT_MAX}
          placeholder="Add a to-do"
          aria-label="New to-do"
          autoComplete="off"
          className="h-11 flex-1 rounded-full bg-secondary px-4"
        />
        <Button type="submit" variant="outline" className="h-11 rounded-full border-input bg-transparent px-5 font-semibold">
          Add
        </Button>
      </form>
      <ul aria-label="To-do" className="mt-1.5 flex flex-col">
        {shown.open.map((item) => (
          <TodoRow
            key={item.id}
            item={item}
            done={false}
            current={item.id === shown.current}
            onChange={(change) => changeTodo(item.id, change)}
            onDelete={() => deleteTodo(item.id)}
          />
        ))}
        {shown.open.length === 0 && (
          <li className="py-3 text-sm text-muted-foreground">{shown.done.length > 0 ? "All done. Nice." : "Nothing to do yet."}</li>
        )}
      </ul>
      {shown.done.length > 0 && <h3 className="label mt-[18px]">Done today</h3>}
      <ul aria-label="Done today" className="mt-1.5 flex flex-col">
        {shown.done.map((item) => (
          <TodoRow
            key={item.id}
            item={item}
            done
            current={false}
            onChange={(change) => changeTodo(item.id, change)}
            onDelete={() => deleteTodo(item.id)}
          />
        ))}
      </ul>
      <h2 className="label today-title">Today</h2>
      <TodayList known={known} now={now} />
    </Card>
  );
}
