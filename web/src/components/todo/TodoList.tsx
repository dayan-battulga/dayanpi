import NumberFlow, { NumberFlowGroup } from "@number-flow/react";
import { AnimatePresence, m } from "motion/react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { riseDelay } from "@/components/shared/rise";
import { AllDone } from "@/components/todo/AllDone";
import { TodoRow } from "@/components/todo/TodoRow";
import { useTodos } from "@/hooks/useTodos";
import { NEW_TODO_ID, TODO_TEXT_MAX } from "@/lib/todos";
import type { FocusState, TodoItem, Todos } from "@/lib/types";

interface TodoListProps {
  todos: Todos | undefined;
  state: FocusState; // tints the current row, and says Working or Paused on it
  now: number;
}

// Desk's to-do list, on the page next to Apps: open rows, the Done ones under them, and the add box at the bottom.
// Checked rows slide between the two lists and the rest close up behind them (Motion layout, the "layout" spring).
export function TodoList({ todos: streamed, state, now }: TodoListProps) {
  const { todos, addTodo, changeTodo, deleteTodo } = useTodos(streamed, now);
  const [newText, setNewText] = useState("");
  // Rows on screen before this render; any other row is one you just added, so it rises in.
  const seen = useRef<Set<string> | null>(null);
  const ids = [...todos.open, ...todos.done].map((item) => item.id);
  useEffect(() => {
    if (streamed != null) {
      seen.current = new Set(ids);
    }
  });
  // "All done" once the open rows run out because they were checked off (not deleted, not on load, not a list that was
  // empty to begin with), until a to-do is open again. Worked out while rendering, so it lands in the same commit as
  // the check: a second commit would hold the checked row's slide into Done for a second.
  const openIds = todos.open.map((item) => item.id);
  const [lastOpen, setLastOpen] = useState<string[] | null>(null);
  const [finished, setFinished] = useState(false);
  if (streamed != null && openIds.join("\n") !== lastOpen?.join("\n")) {
    const doneIds = new Set(todos.done.map((item) => item.id));
    const before = lastOpen ?? [];
    setFinished(openIds.length > 0 ? false : finished || (before.length > 0 && before.every((id) => doneIds.has(id))));
    setLastOpen(openIds);
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = newText.trim();
    if (text !== "") {
      setNewText("");
      const added = await addTodo(text);
      if (!added) {
        setNewText((typed) => typed || text); // back in the box, unless you've started on another
      }
    }
  };
  const showRow = (item: TodoItem, done: boolean) => (
    <TodoRow
      key={item.id}
      item={item}
      done={done}
      current={item.id === todos.current}
      focused={state === "working"}
      isNew={seen.current != null && !seen.current.has(item.id)}
      onChange={(change) => changeTodo(item.id, change)}
      onDelete={() => deleteTodo(item.id)}
    />
  );

  // Like the mockup: with nothing current yet, a nudge to start one; otherwise how many are open.
  const count = todos.open.length;
  let hint: ReactNode = null;
  if (count > 0 && todos.current == null) {
    hint = "Start one to collect its time";
  } else if (count > 0) {
    hint = (
      <>
        <span className="sr-only">{count} open</span>
        <span aria-hidden="true">
          <NumberFlowGroup>
            <NumberFlow value={count} /> open
          </NumberFlowGroup>
        </span>
      </>
    );
  }

  return (
    <section className="todos rise" style={riseDelay(1)} data-state={state} aria-labelledby="todo-title">
      <div className="todos-head">
        <h2 id="todo-title" className="section-title">
          To-do
        </h2>
        <span className="todos-hint">{hint}</span>
      </div>
      <ul className="todo-list" aria-label="To-do">
        <AnimatePresence mode="popLayout" initial={false}>
          {todos.open.map((item) => showRow(item, false))}
        </AnimatePresence>
      </ul>
      {finished && <AllDone />}
      {todos.done.length > 0 && (
        <m.h3 layout="position" className="todo-done-title">
          Done
        </m.h3>
      )}
      <ul className="todo-list is-done" aria-label="Done">
        <AnimatePresence mode="popLayout" initial={false}>
          {todos.done.map((item) => showRow(item, true))}
        </AnimatePresence>
      </ul>
      <m.form layout="position" className="todo-add" onSubmit={submit}>
        <label htmlFor={NEW_TODO_ID} className="sr-only">
          New to-do
        </label>
        <input
          id={NEW_TODO_ID}
          className="todo-add-input"
          value={newText}
          onChange={(event) => setNewText(event.target.value)}
          maxLength={TODO_TEXT_MAX}
          placeholder="Add a to-do"
          autoComplete="off"
        />
      </m.form>
    </section>
  );
}
