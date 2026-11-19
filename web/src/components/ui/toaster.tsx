import { Toaster as SonnerToaster } from "sonner";

export const TOAST_S = 4;

// Sonner as the Calm design's frosted pill (.toast in dashboard.css): bottom right of the page's column (left of the
// sidebar, Frame's --rail-width), centered above the dock on a phone, and one at a time (a newer toast hides the older
// one until it times out).
export function Toaster() {
  return (
    <SonnerToaster
      className="toaster"
      position="bottom-right"
      offset={{ top: 32, right: "calc(32px + var(--rail-width, 0px))", bottom: 32, left: 32 }}
      visibleToasts={1}
      duration={TOAST_S * 1000}
      toastOptions={{ unstyled: true, className: "toast", classNames: { actionButton: "toast-action" } }}
    />
  );
}
