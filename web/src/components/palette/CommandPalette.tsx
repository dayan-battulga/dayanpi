import { useEffect, useRef } from "react";
import { CommandDialog, CommandRow } from "@/components/ui/command";
import type { PaletteCommand } from "@/hooks/useCommands";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  commands: PaletteCommand[];
}

// ⌘K. Frame loads this the first time it opens, then keeps it mounted so it can animate out.
export function CommandPalette({ open, onOpenChange, commands }: CommandPaletteProps) {
  const picked = useRef<PaletteCommand | null>(null);
  // The pick runs once the dialog has closed: while it's open, Radix pulls the focus back from the to-do box N puts it in.
  useEffect(() => {
    const command = picked.current;
    if (!open && command != null) {
      picked.current = null;
      command.run();
    }
  }, [open]);
  const pick = (command: PaletteCommand) => {
    picked.current = command;
    onOpenChange(false);
  };

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Commands" label="Command" placeholder="Type a command">
      {commands.map((command) => (
        <CommandRow key={command.label} label={command.label} shortcut={command.keys.join(" ").toUpperCase()} onSelect={() => pick(command)} />
      ))}
    </CommandDialog>
  );
}
