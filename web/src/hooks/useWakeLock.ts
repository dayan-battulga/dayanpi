import { useEffect } from "react";

// Keeps the screen on while the page is open (the desk sign). The browser lets go of the lock whenever the page is
// hidden, so it asks again each time the page comes back into view. No Wake Lock (an iPad older than iPadOS 16.4) or a
// refusal (low power mode) means the screen just sleeps as usual, with nothing on the page.
export function useWakeLock(): void {
  useEffect(() => {
    let lock: WakeLockSentinel | null = null;
    let current = true;
    const ask = async () => {
      if ("wakeLock" in navigator && document.visibilityState === "visible") {
        try {
          const got = await navigator.wakeLock.request("screen");
          if (current) {
            lock = got;
          } else {
            void got.release().catch(() => undefined);
          }
        } catch {
          // Refused: the screen sleeps on its own schedule.
        }
      }
    };
    const askWhenShown = () => void ask();
    void ask();
    document.addEventListener("visibilitychange", askWhenShown);
    return () => {
      current = false;
      document.removeEventListener("visibilitychange", askWhenShown);
      void lock?.release().catch(() => undefined);
    };
  }, []);
}
