import { useEffect, useState } from "react";
import { request } from "@/lib/http";
import type { FocusState } from "@/lib/types";

export const HIDDEN_CHECK_S = 10; // while the tab is hidden its stream is closed, so the state is checked this often
export const HIDDEN_CHECK_FOR_S = 60 * 60; // for the tab's first hour hidden, then not until it's back

// One SVG per state in web/public/assets: the "d" whose round part is your lamp, in the dark theme's state colors since
// its square is always dark. Signed out it's the gray one, like unknown.
export function findTabIcon(state: FocusState | null): string {
  const icon = `/assets/icon-${state ?? "unknown"}.svg`;
  return icon;
}

// Points index.html's SVG icon at the state's file; the browser redraws the tab when the href changes.
export function showTabIcon(state: FocusState | null): void {
  const link = document.querySelector<HTMLLinkElement>('link[rel="icon"][type="image/svg+xml"]');
  const icon = findTabIcon(state);
  if (link != null && link.getAttribute("href") !== icon) {
    link.setAttribute("href", icon);
  }
}

// The tab's icon follows your state: the stream's while the tab shows, and while it's hidden GET /api/focus every
// HIDDEN_CHECK_S for up to HIDDEN_CHECK_FOR_S. Until the first state comes it stays index.html's.
export function useTabIcon(streamed: FocusState | undefined): void {
  const [checked, setChecked] = useState<FocusState | null>(null);
  useEffect(() => {
    let timer: number | undefined;
    let hiddenAt = 0;
    const check = async () => {
      if (Date.now() - hiddenAt > HIDDEN_CHECK_FOR_S * 1000) {
        window.clearInterval(timer);
      } else {
        const reply = await request<{ state: FocusState }>("GET", "/api/focus");
        // A reply that lands after the tab came back is older than the stream's.
        if (reply.body != null && document.hidden) {
          setChecked(reply.body.state);
        }
      }
    };
    const followVisibility = () => {
      window.clearInterval(timer);
      setChecked(null);
      if (document.hidden) {
        hiddenAt = Date.now();
        timer = window.setInterval(check, HIDDEN_CHECK_S * 1000);
      }
    };
    followVisibility();
    document.addEventListener("visibilitychange", followVisibility);
    return () => {
      document.removeEventListener("visibilitychange", followVisibility);
      window.clearInterval(timer);
    };
  }, []);
  const state = checked ?? streamed;
  useEffect(() => {
    if (state !== undefined) {
      showTabIcon(state);
    }
  }, [state]);
}
