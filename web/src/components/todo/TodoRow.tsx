import { X } from "lucide-react";
import { m } from "motion/react";
import { useRef, useState, type KeyboardEvent, type Ref } from "react";
import { formatDuration } from "@/lib/format";
import { SPRINGS } from "@/lib/motion";
import { TODO_TEXT_MAX, type TodoChange } from "@/lib/todos";
import type { TodoItem } from "@/lib/types";

// A new row rises in; a row leaving fades where it was while the rest slide into its place.
const ROW_HIDDEN = { opacity: 0, y: 10, filter: "blur(4px)" };
const ROW_SHOWN = { opacity: 1, y: 0, filter: "blur(0px)", transitionEnd: { filter: "none" }, transition: SPRINGS.enter };
const ROW_LEAVING = { opacity: 0, transition: SPRINGS.exit };

interface TodoRowProps {
  item: TodoItem;
  done: boolean;
  current: boolean;
  focused: boolean; // Working while you are, Paused otherwise
  isNew: boolean; // just added, so it rises in
  onChange: (change: TodoChange) => void;
  onDelete: () => void;
  ref?: Ref<HTMLLIElement>; // AnimatePresence's popLayout measures the row through it
}

// One to-do, like Desk's: the checkbox, the text (click it to edit), its time, and Start, or Working/Paused on the
// current one. layoutId lets a checked row slide down into Done and back up.
export function TodoRow({ item, done, current, focused, isNew, onChange, onDelete, ref }: TodoRowProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const finished = useRef(false);

  const startEditing = () => {
    finished.current = false;
    setDraft(item.text);
  };
  // Enter, Esc and leaving the box can all land here; only the first one counts.
  const finishEditing = (save: boolean) => {
    const text = (draft ?? "").trim();
    if (!finished.current) {
      finished.current = true;
      if (save && text !== "" && text !== item.text) {
        onChange({ text });
      }
      setDraft(null);
    }
  };
  const handleKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      finishEditing(true);
    } else if (event.key === "Escape") {
      finishEditing(false);
    }
  };

  const pill = focused ? "Working" : "Paused";
  let text = (
    <button type="button" className="todo-text" title="Edit" onClick={startEditing}>
      {item.text}
    </button>
  );
  if (draft != null) {
    text = (
      <input
        autoFocus
        className="todo-edit"
        value={draft}
        maxLength={TODO_TEXT_MAX}
        aria-label={`Edit: ${item.text}`}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={handleKey}
        onBlur={() => finishEditing(true)}
        onFocus={(event) => event.currentTarget.select()}
      />
    );
  }

  return (
    <m.li
      ref={ref}
      layout
      layoutId={`todo-${item.id}`}
      className="todo-row"
      data-current={current || undefined}
      data-done={done || undefined}
      initial={isNew ? ROW_HIDDEN : false}
      animate={ROW_SHOWN}
      exit={ROW_LEAVING}
      transition={{ layout: SPRINGS.layout }}
    >
      <input type="checkbox" className="todo-check" checked={done} onChange={() => onChange({ done: !done })} aria-label={`${done ? "Not done" : "Done"}: ${item.text}`} />
      {text}
      <span className="todo-time">{item.seconds > 0 ? formatDuration(item.seconds) : "—"}</span>
      {!done && current && (
        <button type="button" className="todo-pill" data-working={focused || undefined} aria-pressed="true" aria-label={`Stop working on ${item.text}`} onClick={() => onChange({ current: false })}>
          {pill}
        </button>
      )}
      {!done && !current && (
        <button type="button" className="todo-start" aria-pressed="false" aria-label={`Work on ${item.text}`} onClick={() => onChange({ current: true })}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <polygon points="6 3 20 12 6 21 6 3" />
          </svg>
          Start
        </button>
      )}
      <button type="button" className="todo-delete" aria-label={`Delete ${item.text}`} onClick={onDelete}>
        <X size={16} strokeWidth={1.8} aria-hidden="true" />
      </button>
    </m.li>
  );
}
