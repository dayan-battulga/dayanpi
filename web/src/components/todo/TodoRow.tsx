import { CircleDot, X } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { formatDuration } from "@/lib/format";
import { TODO_TEXT_MAX, type TodoChange } from "@/lib/todos";
import type { TodoItem } from "@/lib/types";
import { cn } from "@/lib/utils";

interface TodoRowProps {
  item: TodoItem;
  done: boolean;
  current: boolean;
  onChange: (change: TodoChange) => void;
  onDelete: () => void;
}

export function TodoRow({ item, done, current, onChange, onDelete }: TodoRowProps) {
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

  return (
    <li className="rise flex min-h-12 items-center gap-2.5 border-b border-border text-sm last:border-b-0">
      <Checkbox
        checked={done}
        onCheckedChange={(checked) => onChange({ done: checked === true })}
        aria-label={`${done ? "Not done" : "Done"}: ${item.text}`}
        className="size-5 cursor-pointer border-muted-foreground data-[state=checked]:border-work data-[state=checked]:bg-work dark:data-[state=checked]:bg-work"
      />
      {draft == null ? (
        <button
          type="button"
          title="Edit"
          onClick={startEditing}
          className={cn(
            "min-w-0 flex-1 cursor-text py-2 text-left [overflow-wrap:anywhere]",
            current && "font-semibold",
            done && "text-muted-foreground line-through",
          )}
        >
          {item.text}
        </button>
      ) : (
        <Input
          autoFocus
          value={draft}
          maxLength={TODO_TEXT_MAX}
          aria-label={`Edit: ${item.text}`}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKey}
          onBlur={() => finishEditing(true)}
          onFocus={(event) => event.currentTarget.select()}
          className="h-9 flex-1 rounded-full bg-secondary px-4"
        />
      )}
      {/* Plain classes, not cn(): tailwind-merge reads text-work as a font size and drops it. */}
      <span className={`mono shrink-0 text-xs ${current ? "text-work" : "text-muted-foreground"}`}>
        {item.seconds > 0 ? formatDuration(item.seconds) : "—"}
      </span>
      {!done && (
        <Button
          variant="ghost"
          size="icon"
          aria-pressed={current}
          aria-label={current ? `Stop working on: ${item.text}` : `Work on: ${item.text}`}
          title={current ? "Current: collecting time while you work" : "Make current"}
          onClick={() => onChange({ current: !current })}
          className="rounded-full text-muted-foreground aria-pressed:text-work"
        >
          <CircleDot strokeWidth={1.8} />
        </Button>
      )}
      <Button variant="ghost" size="icon" aria-label={`Delete: ${item.text}`} onClick={onDelete} className="rounded-full text-muted-foreground">
        <X strokeWidth={1.8} />
      </Button>
    </li>
  );
}
