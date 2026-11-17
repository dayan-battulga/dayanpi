import { Suspense, ViewTransition, useLayoutEffect } from "react";
import { Outlet, useLocation, useOutletContext } from "react-router";
import { Dock } from "@/components/header/Dock";
import { Header } from "@/components/header/Header";
import { GestureToast } from "@/components/shared/GestureToast";
import { useMe } from "@/hooks/useMe";
import { PHONE_QUERY, useMediaQuery } from "@/hooks/useMediaQuery";
import { useNow } from "@/hooks/useNow";
import { useSnapshot } from "@/hooks/useSnapshot";
import type { Connection, Snapshot, User } from "@/lib/types";

// What every page inside the frame gets: the one stream, who you are, and a clock that never runs backwards.
export interface FrameData {
  snapshot: Snapshot | null;
  connection: Connection;
  receivedAt: number;
  now: number;
  user: User | null;
  setUser: (user: User) => void;
}

export function useFrame(): FrameData {
  return useOutletContext<FrameData>();
}

// Every signed-in page: the top bar, the page itself (which cross-fades when it changes), and the dock on a phone.
export function Frame() {
  const { snapshot, connection, receivedAt } = useSnapshot();
  const { user, setUser } = useMe();
  const clock = useNow();
  const phone = useMediaQuery(PHONE_QUERY);
  const { pathname } = useLocation();
  // A snapshot can land between two ticks of the clock; never show time running backwards.
  const now = Math.max(clock, receivedAt);
  const frame: FrameData = { snapshot, connection, receivedAt, now, user, setUser };
  // Before the new page is drawn, so it starts at its top instead of wherever the last one was scrolled to.
  useLayoutEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <div className="frame" data-connection={connection}>
      <Header connection={connection} user={user} phone={phone} />
      {/* Suspense outside the keyed page, so a lazy page keeps the old one up while it loads instead of a blank. */}
      <Suspense fallback={null}>
        <ViewTransition key={pathname} enter="page" exit="page" default="none">
          <main className="shell">
            <Outlet context={frame} />
          </main>
        </ViewTransition>
      </Suspense>
      {phone && <Dock canAdd={user?.role === "owner"} />}
      <GestureToast gesture={snapshot?.focus?.gesture} now={now} receivedAt={receivedAt} />
    </div>
  );
}
