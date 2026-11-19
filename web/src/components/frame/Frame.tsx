import { m, useReducedMotionConfig } from "motion/react";
import { Suspense, ViewTransition, lazy, useCallback, useLayoutEffect, useState } from "react";
import { Outlet, useLocation, useOutletContext } from "react-router";
import { PeacePill } from "@/components/frame/PeacePill";
import { Dock } from "@/components/header/Dock";
import { Header } from "@/components/header/Header";
import { RoomBar, RoomRail } from "@/components/room/WhoIsHere";
import { Toaster } from "@/components/ui/toaster";
import { type Camera, useCamera } from "@/hooks/useCamera";
import { useCommands, useShortcuts } from "@/hooks/useCommands";
import { useGestureToast } from "@/hooks/useGestureToast";
import { usePeaceVoice } from "@/hooks/usePeaceVoice";
import { type MacTracking, useMacTracking } from "@/hooks/useMacTracking";
import { useMe } from "@/hooks/useMe";
import { PHONE_QUERY, WIDE_QUERY, useMediaQuery } from "@/hooks/useMediaQuery";
import { useNudgeToast } from "@/hooks/useNudge";
import { useNow } from "@/hooks/useNow";
import { useSnapshot } from "@/hooks/useSnapshot";
import { SPRINGS } from "@/lib/motion";
import { listOthersHere, orderSeats, summarizeRoom } from "@/lib/room";
import { readStored, writeStored } from "@/lib/storage";
import type { Connection, Snapshot, User } from "@/lib/types";

// The pages that show who's here, in the sidebar or the bottom bar. The room and their desks show it themselves.
const PAGES_WITH_ROOM = new Set(["/me", "/pi", "/settings"]);
// The sidebar's width open and folded: dashboard.css's .rail and .rail-collapsed.
const RAIL_PX = { open: 360, collapsed: 76 };

const CommandPalette = lazy(() => import("@/components/palette/CommandPalette").then((module) => ({ default: module.CommandPalette })));

// What every page inside the frame gets: the one stream, who you are, a clock that never runs backwards, the Mac
// tracking pick (shared with ⌘K) and this browser's camera.
export interface FrameData {
  snapshot: Snapshot | null;
  connection: Connection;
  receivedAt: number;
  now: number;
  user: User | null;
  setUser: (user: User) => void;
  macTracking: MacTracking;
  camera: Camera;
}

export function useFrame(): FrameData {
  return useOutletContext<FrameData>();
}

// Every signed-in page: the top bar and the page itself (which cross-fades when it changes) in one column, who's here
// (from 1280 px the sidebar on the window's right edge, the bottom bar down to a phone), the peace sign's pill, the dock on a phone, ⌘K and the toasts. The camera
// lives here too, so it keeps running from page to page and in the background.
export function Frame() {
  const { snapshot, connection, receivedAt } = useSnapshot();
  const { user, setUser } = useMe();
  const clock = useNow();
  const phone = useMediaQuery(PHONE_QUERY);
  const wide = useMediaQuery(WIDE_QUERY);
  const reduced = useReducedMotionConfig();
  const [collapsed, setCollapsed] = useState(() => readStored("rail", "open") === "collapsed");
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
  useNudgeToast(snapshot?.focus?.spoken);
  const camera = useCamera(snapshot?.focus?.camera_source);
  // A hidden tab's stream is closed, but the camera's readings still bring the peace sign's message, so its clip plays.
  const shownSpoken = snapshot?.focus?.spoken;
  const peaceVoice = usePeaceVoice((camera.spoken?.at ?? -1) > (shownSpoken?.at ?? -1) ? camera.spoken : shownSpoken);
  const frame: FrameData = { snapshot, connection, receivedAt, now, user, setUser, macTracking, camera };
  const seats = orderSeats(snapshot?.room?.seats ?? [], user?.username);
  const room = summarizeRoom(seats);
  const others = listOthersHere(seats, user?.username);
  const elapsed = Math.max(0, now - receivedAt);
  // The sidebar holds its place once anyone else has an account, so the page doesn't jump as people come and go; the
  // bottom bar floats, so it only comes when someone's here.
  const withRoom = PAGES_WITH_ROOM.has(pathname);
  const rail = withRoom && wide && seats.length > 1 ? (collapsed ? "collapsed" : "open") : undefined;
  const bar = withRoom && !wide && !phone && others.length > 0;
  const railWidth = rail == null ? 0 : RAIL_PX[rail];
  const collapseRail = (folded: boolean) => {
    setCollapsed(folded);
    writeStored("rail", folded ? "collapsed" : "open");
  };
  // Before the new page is drawn, so it starts at its top instead of wherever the last one was scrolled to.
  useLayoutEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    // --rail-width is the room the sidebar takes on the right. It springs, so the column (and the peace pill and toasts
    // over it) eases over as the sidebar comes, goes or folds, instead of jumping.
    <m.div
      className="frame"
      data-connection={connection}
      data-rail={rail}
      data-bar={bar ? "" : undefined}
      initial={false}
      animate={{ "--rail-width": `${railWidth}px` }}
      transition={reduced ? { duration: 0 } : SPRINGS.layout}
    >
      <div className="frame-column">
        <Header
          connection={connection}
          user={user}
          phone={phone}
          here={pathname === "/" ? room.here : null}
          hereLabel={room.hereLabel}
          onOpenPalette={() => setPaletteOpen(true)}
        />
        {/* Suspense outside the keyed page, so a lazy page keeps the old one up while it loads instead of a blank. */}
        <Suspense fallback={null}>
          <ViewTransition key={pathname} enter="page" exit="page" default="none">
            <main className="shell">
              <Outlet context={frame} />
            </main>
          </ViewTransition>
        </Suspense>
      </div>
      {wide && (
        <div className="rail-slot">
          {rail != null && <RoomRail others={others} elapsed={elapsed} together={room.focusSeconds} collapsed={rail === "collapsed"} onCollapse={collapseRail} />}
        </div>
      )}
      {bar && <RoomBar others={others} elapsed={elapsed} />}
      <PeacePill spoken={snapshot?.focus?.spoken} receivedAt={receivedAt} now={now} voice={peaceVoice} />
      {phone && <Dock />}
      {palette.used && (
        <Suspense fallback={null}>
          <CommandPalette open={palette.open} onOpenChange={setPaletteOpen} commands={commands} />
        </Suspense>
      )}
      <Toaster />
    </m.div>
  );
}
