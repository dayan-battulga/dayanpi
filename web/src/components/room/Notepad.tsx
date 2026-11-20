import { X } from "lucide-react";
import { AnimatePresence, m } from "motion/react";
import { Dialog } from "radix-ui";
import { useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import { Link } from "react-router";
import { EdgePanel } from "@/components/shared/EdgePanel";
import { PriorityChip } from "@/components/todo/PriorityChip";
import { PopDialog } from "@/components/ui/dialog";
import { PHONE_QUERY, useMediaQuery } from "@/hooks/useMediaQuery";
import { useTodos } from "@/hooks/useTodos";
import { SPRINGS } from "@/lib/motion";
import { SHOW_EVERY_PRIORITY, TODO_TEXT_MAX, describeShown, listNotepad } from "@/lib/todos";
import type { FocusStatus, Priority } from "@/lib/types";

// Below 1280 px the notepad is a sheet: from the right on a laptop, from the bottom on a phone (SPEC's slide).
const FROM_SIDE = { opacity: 0, x: 24 };
const FROM_BOTTOM = { opacity: 0, y: 24 };
const ROW_IN = { opacity: 1, transition: SPRINGS.enter };
const ROW_OUT = { opacity: 0, transition: SPRINGS.exit };

// RoomV2's to-do icon: three lines, each with a check.
function NotepadIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 6h11M9 12h11M9 18h11m-17-12 1 1 2-2m-3 7 1 1 2-2m-3 7 1 1 2-2" />
    </svg>
  );
}

interface NotepadProps {
  focus: FocusStatus | undefined; // your own desk's: only you ever see the notepad
  now: number;
}

interface NotepadContentsProps extends NotepadProps {
  kept: string[]; // added from the notepad this visit: they stay on it, whatever Settings → To-dos shows, until they get a priority
  setKept: Dispatch<SetStateAction<string[]>>;
}

function countShown(focus: FocusStatus | undefined, kept: string[]): number {
  const listed = listNotepad(focus?.todos ?? { current: null, open: [], done: [] }, focus?.notepad ?? SHOW_EVERY_PRIORITY, kept);
  const count = listed.rows.length + (listed.current == null ? 0 : 1);
  return count;
}

// The notepad (RoomV2.dc.html): which priorities show, what you're working on first, the rest by priority with their
// chips, and the add box. Checking one off sends it to Done on your Desk.
function NotepadContents({ focus, now, kept, setKept }: NotepadContentsProps) {
  const { todos, addTodo, changeTodo } = useTodos(focus?.todos, now);
  const shown = focus?.notepad ?? SHOW_EVERY_PRIORITY;
  const { current, rows } = listNotepad(todos, shown, kept);
  const [newText, setNewText] = useState("");
  const working = focus?.state === "working";

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = newText.trim();
    if (text !== "") {
      setNewText("");
      const added = await addTodo(text);
      if (added == null) {
        setNewText((typed) => typed || text);
      } else {
        setKept((ids) => [...ids, added]);
      }
    }
  };
  const pick = (id: string, priority: Priority) => {
    changeTodo(id, { priority });
    if (priority !== "none") {
      setKept((ids) => ids.filter((keptId) => keptId !== id));
    }
  };

  return (
    <>
      <p className="notepad-sub">
        {describeShown(shown)} · only you see this ·{" "}
        <Link className="notepad-change" to="/settings" state={{ section: "todos" }}>
          change
        </Link>
      </p>
      {current != null && (
        <div className="notepad-current" data-working={working || undefined}>
          <input type="checkbox" className="todo-check" checked={false} onChange={() => changeTodo(current.id, { done: true })} aria-label={`Done: ${current.text}`} />
          <span className="notepad-text">{current.text}</span>
          <span className="notepad-working">{working ? "Working" : "Paused"}</span>
        </div>
      )}
      <ul className="notepad-list" aria-label="Your to-dos">
        <AnimatePresence mode="popLayout" initial={false}>
          {rows.map((item) => (
            <m.li key={item.id} layout className="notepad-row" initial={{ opacity: 0 }} animate={ROW_IN} exit={ROW_OUT} transition={{ layout: SPRINGS.layout }}>
              <input type="checkbox" className="todo-check" checked={false} onChange={() => changeTodo(item.id, { done: true })} aria-label={`Done: ${item.text}`} />
              <span className="notepad-text">{item.text}</span>
              <PriorityChip priority={item.priority ?? "none"} text={item.text} onPick={(priority) => pick(item.id, priority)} />
            </m.li>
          ))}
        </AnimatePresence>
      </ul>
      <form className="notepad-add" onSubmit={submit}>
        <label htmlFor="notepad-new" className="sr-only">
          New to-do
        </label>
        <input
          id="notepad-new"
          className="notepad-add-input"
          value={newText}
          onChange={(event) => setNewText(event.target.value)}
          maxLength={TODO_TEXT_MAX}
          placeholder="Add a to-do"
          autoComplete="off"
        />
        <span className="notepad-enter" aria-hidden="true">
          ↵
        </span>
      </form>
      <p className="notepad-note">New to-dos start with no priority. Pick one from its menu.</p>
    </>
  );
}

interface NotepadPanelProps extends NotepadProps {
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
}

// From 1280 px: the notepad pinned to the window's right edge, the room sidebar's panel. Folded, a to-do button with
// how many it lists.
export function NotepadPanel({ focus, now, collapsed, onCollapse }: NotepadPanelProps) {
  const [kept, setKept] = useState<string[]>([]);
  const count = countShown(focus, kept);
  const strip = (
    <button type="button" className="notepad-strip" aria-label={`Open the notepad: ${count} to-dos`} onClick={() => onCollapse(false)}>
      <NotepadIcon />
      {count > 0 && (
        <span className="notepad-count" aria-hidden="true">
          {count}
        </span>
      )}
    </button>
  );
  return (
    <EdgePanel
      title="Notepad"
      titleId="notepad-title"
      stripLabel="Notepad"
      foldLabel="Fold the notepad"
      openLabel="Open the notepad"
      className="rail-notepad"
      collapsed={collapsed}
      onCollapse={onCollapse}
      strip={strip}
    >
      <NotepadContents focus={focus} now={now} kept={kept} setKept={setKept} />
    </EdgePanel>
  );
}

// Below 1280 px: a Notepad button that opens the same notepad as a sheet.
export function NotepadSheet({ focus, now }: NotepadProps) {
  const [open, setOpen] = useState(false);
  const [kept, setKept] = useState<string[]>([]);
  const phone = useMediaQuery(PHONE_QUERY);
  return (
    <>
      <button type="button" className="button button-line notepad-open" aria-haspopup="dialog" onClick={() => setOpen(true)}>
        <NotepadIcon />
        Notepad
      </button>
      <PopDialog open={open} onOpenChange={setOpen} className="notepad-sheet" hidden={phone ? FROM_BOTTOM : FROM_SIDE}>
        <div className="rail-head">
          <Dialog.Title className="rail-title">Notepad</Dialog.Title>
          <Dialog.Close className="rail-toggle" aria-label="Close">
            <X size={18} strokeWidth={1.8} aria-hidden="true" />
          </Dialog.Close>
        </div>
        <NotepadContents focus={focus} now={now} kept={kept} setKept={setKept} />
      </PopDialog>
    </>
  );
}
