import { AnimatePresence, m, useReducedMotion } from "motion/react";
import { Dialog } from "radix-ui";
import type { ReactNode } from "react";
import { SPRINGS } from "@/lib/motion";

// SPEC's "pop": every dialog comes from here and goes back to it.
const POPPED_OUT = { opacity: 0, y: 16, scale: 0.97 };

interface PopDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  className: string; // the card's, which places it
  onCloseAutoFocus?: (event: Event) => void;
  children: ReactNode; // with a Dialog.Title somewhere
}

// Our Radix Dialog: a solid card over the blurred scrim, popping in and out. Esc and the scrim close it.
export function PopDialog({ open, onOpenChange, className, onCloseAutoFocus, children }: PopDialogProps) {
  // Reduced motion skips the pop on the way in but would snap to it on the way out, so leaving is a plain fade then.
  const leaving = useReducedMotion() ? { opacity: 0 } : POPPED_OUT;
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay forceMount asChild>
              <m.div className="scrim" initial={{ opacity: 0 }} animate={{ opacity: 1, transition: { duration: 0.3 } }} exit={{ opacity: 0, transition: SPRINGS.exit }} />
            </Dialog.Overlay>
            <Dialog.Content forceMount asChild aria-describedby={undefined} onCloseAutoFocus={onCloseAutoFocus}>
              <m.div className={className} initial={POPPED_OUT} animate={{ opacity: 1, y: 0, scale: 1, transition: SPRINGS.enter }} exit={{ ...leaving, transition: SPRINGS.exit }}>
                {children}
              </m.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}
