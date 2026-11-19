import { Toaster as SonnerToaster } from "sonner";

export const TOAST_S = 4;

// Sonner as the Calm design's frosted pill (.toast in dashboard.css): bottom right, centered above the dock on a phone,
// and one at a time (a newer toast hides the older one until it times out).
export function Toaster() {
  return (
    <SonnerToaster
      className="toaster"
      position="bottom-right"
      offset={32}
      visibleToasts={1}
      duration={TOAST_S * 1000}
      toastOptions={{ unstyled: true, className: "toast", classNames: { actionButton: "toast-action" } }}
    />
  );
}
