import { Command, useCommandState } from "cmdk";
import { Search } from "lucide-react";
import { m } from "motion/react";
import { Dialog } from "radix-ui";
import type { ReactNode } from "react";
import { PopDialog } from "@/components/ui/dialog";
import { SPRINGS } from "@/lib/motion";

// When what was picked moved the focus itself (N into the to-do box), leave it there instead of going back to the
// button that opened the dialog. A focus still inside the closed dialog is gone with it by now.
function keepMovedFocus(event: Event): void {
  const focused = document.activeElement;
  if (focused != null && focused !== document.body && focused.isConnected) {
    event.preventDefault();
  }
}

interface CommandDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  label: string; // the search field's
  placeholder: string;
  children: ReactNode; // CommandRows
}

// cmdk inside our own Radix Dialog (not shadcn's, see CLAUDE.md): a solid card over the scrim, popping in and out.
// Typing filters, ↑/↓ wrap around, Enter picks, Esc closes.
export function CommandDialog({ open, onOpenChange, title, label, placeholder, children }: CommandDialogProps) {
  return (
    <PopDialog open={open} onOpenChange={onOpenChange} className="palette" onCloseAutoFocus={keepMovedFocus}>
      <Dialog.Title className="sr-only">{title}</Dialog.Title>
      {/* Ctrl+K is the palette's own shortcut, so cmdk's Ctrl+J/K/N/P moves are off. */}
      <Command label={label} loop vimBindings={false}>
        <div className="palette-search">
          <Search size={18} strokeWidth={1.8} aria-hidden="true" />
          <Command.Input className="palette-input" placeholder={placeholder} />
          <kbd className="palette-key">esc</kbd>
        </div>
        <Command.List className="palette-list">
          <Command.Empty className="palette-empty">Nothing matches</Command.Empty>
          {children}
        </Command.List>
      </Command>
    </PopDialog>
  );
}

interface CommandRowProps {
  label: string;
  shortcut: string; // shown on the right, "" for none
  onSelect: () => void;
}

// One row. The highlighted one carries the highlight, which slides to the next on the toggle spring.
export function CommandRow({ label, shortcut, onSelect }: CommandRowProps) {
  const highlighted = useCommandState((state) => state.value === label);
  return (
    <Command.Item className="palette-row" value={label} onSelect={onSelect}>
      {highlighted && <m.span layoutId="palette-highlight" className="palette-highlight" transition={SPRINGS.toggle} />}
      <span className="palette-label">{label}</span>
      {shortcut && <kbd className="palette-key">{shortcut}</kbd>}
    </Command.Item>
  );
}
