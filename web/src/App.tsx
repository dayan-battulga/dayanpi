import { CalendarCard } from "@/components/calendar/CalendarCard";
import { CameraCard } from "@/components/camera/CameraCard";
import { FocusCard } from "@/components/focus/FocusCard";
import { Header } from "@/components/header/Header";
import { PiSection } from "@/components/pi/PiSection";
import { GestureToast } from "@/components/shared/GestureToast";
import { TodoCard } from "@/components/todo/TodoCard";
import { useFocusSegments } from "@/hooks/useFocusSegments";
import { useNow } from "@/hooks/useNow";
import { useSnapshot } from "@/hooks/useSnapshot";
import { useTheme } from "@/hooks/useTheme";
import { mergeKnownSegments, readLocalMidnight } from "@/lib/timeline";

export function App() {
  const { snapshot, connection, receivedAt } = useSnapshot();
  const clock = useNow();
  // A snapshot can land between two ticks of the clock; never show time running backwards.
  const now = Math.max(clock, receivedAt);
  const focus = snapshot?.focus;
  const { segments, loaded } = useFocusSegments(focus?.state);
  const midnight = readLocalMidnight(now);
  const known = mergeKnownSegments(segments, midnight);
  const { theme, toggleTheme } = useTheme();

  return (
    <div className="shell">
      <Header connection={connection} undervoltage={snapshot?.throttle.is_undervoltage ?? false} theme={theme} onToggleTheme={toggleTheme} />
      <FocusCard focus={focus} segments={segments} known={known} loaded={loaded} now={now} midnight={midnight} receivedAt={receivedAt} />
      <div className="row">
        <CameraCard focus={focus} />
        <TodoCard todos={focus?.todos} known={known} now={now} />
      </div>
      <CalendarCard todayFocusSeconds={focus?.today.working_seconds} now={now} />
      <PiSection stats={snapshot} now={now} />
      <footer className="footer mono muted small">
        <span>dayanpi · served from the Pi on your desk</span>
        <span>tailscale serve · private</span>
      </footer>
      <GestureToast gesture={focus?.gesture} now={now} receivedAt={receivedAt} />
    </div>
  );
}
