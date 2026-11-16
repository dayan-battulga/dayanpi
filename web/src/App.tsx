import { AppsCard } from "@/components/apps/AppsCard";
import { CalendarCard } from "@/components/calendar/CalendarCard";
import { CameraCard } from "@/components/camera/CameraCard";
import { FocusCard } from "@/components/focus/FocusCard";
import { Header } from "@/components/header/Header";
import { MacCard } from "@/components/mac/MacCard";
import { PiSection } from "@/components/pi/PiSection";
import { GestureToast } from "@/components/shared/GestureToast";
import { TodoCard } from "@/components/todo/TodoCard";
import { useFocusSegments } from "@/hooks/useFocusSegments";
import { useMe } from "@/hooks/useMe";
import { useNow } from "@/hooks/useNow";
import { useSnapshot } from "@/hooks/useSnapshot";
import { readPiStats } from "@/lib/pi";
import { mergeKnownSegments, readLocalMidnight } from "@/lib/timeline";

// The dashboard, at "/".
export function App() {
  const { snapshot, connection, receivedAt } = useSnapshot();
  const { user } = useMe();
  const clock = useNow();
  // A snapshot can land between two ticks of the clock; never show time running backwards.
  const now = Math.max(clock, receivedAt);
  const focus = snapshot?.focus;
  const { segments, loaded } = useFocusSegments(focus?.state);
  const midnight = readLocalMidnight(now);
  const known = mergeKnownSegments(segments, midnight);
  const piStats = readPiStats(snapshot);
  // Members get no Pi numbers in the stream; before the first snapshot only the owner sees "Connecting…".
  const piShown = snapshot == null ? user?.role !== "member" : piStats != null;
  // Members can look at the owner's things but not change them (the Pi would 403 anyway).
  const readOnly = user?.role !== "owner";

  return (
    <div className="shell">
      <Header connection={connection} undervoltage={piStats?.throttle.is_undervoltage ?? false} user={user} piShown={piShown} />
      <MacCard focus={focus} now={now} readOnly={readOnly} />
      <FocusCard focus={focus} segments={segments} known={known} loaded={loaded} now={now} midnight={midnight} receivedAt={receivedAt} />
      <AppsCard now={now} />
      <div className="row">
        <CameraCard focus={focus} />
        <TodoCard todos={focus?.todos} known={known} now={now} readOnly={readOnly} />
      </div>
      <CalendarCard todayFocusSeconds={focus?.today.working_seconds} now={now} />
      {piShown && <PiSection stats={piStats} focus={focus} />}
      <footer className="footer mono muted small">
        <span>dayanpi · served from the Pi on your desk</span>
        <span>invite only · private</span>
      </footer>
      <GestureToast gesture={focus?.gesture} now={now} receivedAt={receivedAt} />
    </div>
  );
}
