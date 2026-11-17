import { Plus, Settings2 } from "lucide-react";
import { useNavigate } from "react-router";
import { PillLink } from "@/components/header/Header";
import { openNewTodo } from "@/lib/todos";

// On a phone the pages sit in a frosted dock at the bottom (RoomPhone), with a + for a new to-do.
export function Dock({ canAdd }: { canAdd: boolean }) {
  const navigate = useNavigate();
  const addTodo = () => openNewTodo(navigate);
  return (
    <nav className="dock" aria-label="Pages">
      <PillLink to="/me" kind="dock" label="Desk">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </svg>
      </PillLink>
      {canAdd && (
        <button type="button" className="dock-add" aria-label="New to-do" onClick={addTodo}>
          <Plus size={20} strokeWidth={2} aria-hidden="true" />
        </button>
      )}
      <PillLink to="/settings" kind="dock" label="Settings">
        <Settings2 size={20} strokeWidth={1.8} aria-hidden="true" />
      </PillLink>
    </nav>
  );
}
