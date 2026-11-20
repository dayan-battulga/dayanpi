import { Switch } from "@/components/ui/switch";
import { useHeldReply } from "@/hooks/useHeldReply";
import { request } from "@/lib/http";
import { SHOW_EVERY_PRIORITY } from "@/lib/todos";
import type { FocusStatus, Priority } from "@/lib/types";

const LEVELS: { value: Priority; label: string }[] = [
  { value: "high", label: "High priority" },
  { value: "medium", label: "Medium priority" },
  { value: "low", label: "Low priority" },
  { value: "none", label: "No priority" },
];

// Settings → To-dos (RoomNotepad.dc.html): which priorities the Room's notepad shows, all four until you switch one off.
// A flip shows at once and the Pi's reply holds against a late snapshot, like the sharing switches.
export function TodosSection({ focus, now }: { focus: FocusStatus | undefined; now: number }) {
  const { shown, send } = useHeldReply(focus?.notepad ?? SHOW_EVERY_PRIORITY, now);
  const flip = (priority: Priority, on: boolean) => {
    const ask = async () => (await request<Record<Priority, boolean>>("POST", "/api/notepad", { [priority]: on })).body;
    void send({ ...shown, [priority]: on }, ask, "Couldn't change the notepad");
  };

  return (
    <section className="todo-levels" aria-labelledby="settings-todos">
      <h2 id="settings-todos" className="settings-title">
        To-dos
      </h2>
      <p className="todo-levels-label">Show in the Room’s notepad</p>
      <ul>
        {LEVELS.map((level) => (
          <li key={level.value} className="setting-row">
            <span className="todo-level" data-priority={level.value}>
              <span className="priority-dot" aria-hidden="true" />
              {level.label}
            </span>
            <Switch label={level.label} checked={shown[level.value]} onCheckedChange={(on) => flip(level.value, on)} />
          </li>
        ))}
      </ul>
      <p className="todo-levels-note">What you’re working on always shows first. Your Desk always shows every to-do.</p>
      <p className="todo-levels-more">
        Everything shows unless you turn a priority off. New to-dos start with no priority; change one any time from the small priority menu on the to-do,
        on the notepad or your Desk. A to-do you add from the notepad stays on it until you give it a priority.
      </p>
    </section>
  );
}
