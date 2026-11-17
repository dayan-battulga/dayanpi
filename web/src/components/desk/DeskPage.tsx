import { useEffect } from "react";
import { useLocation } from "react-router";
import { AppsCard } from "@/components/apps/AppsCard";
import { CalendarCard } from "@/components/calendar/CalendarCard";
import { FocusNow } from "@/components/focus/FocusNow";
import { useFrame } from "@/components/frame/Frame";
import { TodoCard } from "@/components/todo/TodoCard";
import { useFocusSegments } from "@/hooks/useFocusSegments";
import { mergeKnownSegments, readLocalMidnight } from "@/lib/timeline";
import { focusNewTodo } from "@/lib/todos";

// My desk, at /me: today's cards.
export function DeskPage() {
  const { snapshot, receivedAt, now, user, macTracking } = useFrame();
  const focus = snapshot?.focus;
  const { segments, loaded } = useFocusSegments(focus?.state);
  const midnight = readLocalMidnight(now);
  const known = mergeKnownSegments(segments, midnight);
  // Members can look at the owner's things but not change them (the Pi would 403 anyway).
  const readOnly = user?.role !== "owner";
  // The dock's + from another page lands here asking for the new to-do box.
  const addTodo = (useLocation().state as { addTodo?: number } | null)?.addTodo;
  useEffect(() => {
    if (addTodo != null) {
      focusNewTodo();
    }
  }, [addTodo]);

  return (
    <div className="live">
      <FocusNow focus={focus} known={known} loaded={loaded} now={now} midnight={midnight} receivedAt={receivedAt} macTracking={macTracking} readOnly={readOnly} />
      <AppsCard now={now} />
      <div className="row">
        <TodoCard todos={focus?.todos} known={known} now={now} readOnly={readOnly} />
      </div>
      <CalendarCard todayFocusSeconds={focus?.today.working_seconds} now={now} />
    </div>
  );
}
