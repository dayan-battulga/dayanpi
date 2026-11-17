import { Suspense, ViewTransition, lazy, useCallback, useLayoutEffect, useState } from "react";
import { Outlet, useLocation, useOutletContext } from "react-router";
import { Dock } from "@/components/header/Dock";
import { Header } from "@/components/header/Header";
import { Toaster } from "@/components/ui/toaster";
import { useCommands, useShortcuts } from "@/hooks/useCommands";
import { useGestureToast } from "@/hooks/useGestureToast";
import { type MacTracking, useMacTracking } from "@/hooks/useMacTracking";
import { useMe } from "@/hooks/useMe";
import { PHONE_QUERY, useMediaQuery } from "@/hooks/useMediaQuery";
import { useNow } from "@/hooks/useNow";
import { useSnapshot } from "@/hooks/useSnapshot";
import type { Connection, Snapshot, User } from "@/lib/types";

const CommandPalette = lazy(() => import("@/components/palette/CommandPalette").then((module) => ({ default: module.CommandPalette })));

// What every page inside the frame gets: the one stream, who you are, a clock that never runs backwards, and the
// Mac tracking pick (shared with ⌘K).
export interface FrameData {
  snapshot: Snapshot | null;
  connection: Connection;
  receivedAt: number;
  now: number;
  user: User | null;
  setUser: (user: User) => void;
  macTracking: MacTracking;
}

export function useFrame(): FrameData {
  return useOutletContext<FrameData>();
}

// Every signed-in page: the top bar, the page itself (which cross-fades when it changes), the dock on a phone, ⌘K and
// the toasts.
export function Frame() {
  const { snapshot, connection, receivedAt } = useSnapshot();
  const { user, setUser } = useMe();
  const clock = useNow();
  const phone = useMediaQuery(PHONE_QUERY);
  const { pathname } = useLocation();
  // A snapshot can land between two ticks of the clock; never show time running backwards.
  const now = Math.max(clock, receivedAt);
  const macTracking = useMacTracking(snapshot?.focus, now);
  const commands = useCommands({ user, hasFocus: snapshot?.focus != null, macTracking });
  // The palette's code only downloads the first time it opens ("used"), and then stays.
  const [palette, setPalette] = useState({ open: false, used: false });
  const setPaletteOpen = useCallback((open: boolean) => setPalette({ open, used: true }), []);
  const togglePalette = useCallback(() => setPalette((current) => ({ open: !current.open, used: true })), []);
  useShortcuts(commands, togglePalette);
  useGestureToast(snapshot?.focus?.gesture);
  const frame: FrameData = { snapshot, connection, receivedAt, now, user, setUser, macTracking };
  // Before the new page is drawn, so it starts at its top instead of wherever the last one was scrolled to.
  useLayoutEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <div className="frame" data-connection={connection}>
      <Header connection={connection} user={user} phone={phone} onOpenPalette={() => setPaletteOpen(true)} />
      {/* Suspense outside the keyed page, so a lazy page keeps the old one up while it loads instead of a blank. */}
      <Suspense fallback={null}>
        <ViewTransition key={pathname} enter="page" exit="page" default="none">
          <main className="shell">
            <Outlet context={frame} />
          </main>
        </ViewTransition>
      </Suspense>
      {phone && <Dock canAdd={user?.role === "owner"} />}
      {palette.used && (
        <Suspense fallback={null}>
          <CommandPalette open={palette.open} onOpenChange={setPaletteOpen} commands={commands} />
        </Suspense>
      )}
      <Toaster />
    </div>
  );
}
