import { useEffect, useRef } from "react";
import { useNavigate } from "react-router";
import type { MacTracking } from "@/hooks/useMacTracking";
import { useTheme } from "@/hooks/useTheme";
import { openNewTodo } from "@/lib/todos";
import type { User } from "@/lib/types";

// A second key counts as part of a "G D" only this soon after the G.
const SEQUENCE_MS = 1000;

export interface PaletteCommand {
  label: string;
  keys: string[]; // pressed one after the other (["g", "d"]); empty for no shortcut
  run: () => void;
}

interface CommandSources {
  user: User | null;
  hasFocus: boolean; // the stream has said what the tracking is
  macTracking: MacTracking;
}

// What ⌘K lists and what its shortcuts do. Owner-only things only show for the owner, the same as on the page.
export function useCommands({ user, hasFocus, macTracking }: CommandSources): PaletteCommand[] {
  const navigate = useNavigate();
  const { toggleTheme } = useTheme();
  const owner = user?.role === "owner";
  const { tracking, flipTracking } = macTracking;
  const all = [
    { label: "Add a to-do", keys: ["n"], run: () => openNewTodo(navigate), shown: true },
    { label: "Go to Desk", keys: ["g", "d"], run: () => void navigate("/me"), shown: true },
    { label: "Go to Pi", keys: ["g", "p"], run: () => void navigate("/pi"), shown: owner },
    { label: "Go to Settings", keys: ["g", "s"], run: () => void navigate("/settings"), shown: true },
    { label: "Switch theme", keys: ["t"], run: toggleTheme, shown: true },
    { label: tracking ? "Pause Mac tracking" : "Resume Mac tracking", keys: [], run: () => void flipTracking(!tracking), shown: hasFocus },
  ];
  const commands = all.filter((command) => command.shown).map(({ label, keys, run }) => ({ label, keys, run }));
  return commands;
}

function isTyping(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || target.closest("input, textarea, select") != null);
}

function matchKeys(commands: PaletteCommand[], pressed: string[]): PaletteCommand | undefined {
  return commands.find((command) => command.keys.length === pressed.length && command.keys.every((key, index) => key === pressed[index]));
}

// ⌘K or Ctrl+K toggles the palette from anywhere, even a text box. A command's own keys only count when you're not
// typing, and never with ⌘, Ctrl or Alt held, so they can't fight the browser's or a field's.
export function useShortcuts(commands: PaletteCommand[], togglePalette: () => void): void {
  const latest = useRef(commands);
  useEffect(() => {
    latest.current = commands;
  });

  useEffect(() => {
    let previous = { key: "", at: -Infinity };
    const handleKey = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      const plain = !event.metaKey && !event.ctrlKey && !event.altKey && !event.repeat && !isTyping(event.target);
      if ((event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && key === "k") {
        event.preventDefault();
        togglePalette();
      } else if (plain) {
        const second = event.timeStamp - previous.at < SEQUENCE_MS ? matchKeys(latest.current, [previous.key, key]) : undefined;
        const command = second ?? matchKeys(latest.current, [key]);
        // Without this, N would also type an "n" into the to-do box it just focused.
        if (command != null) {
          event.preventDefault();
          command.run();
        }
        previous = command == null ? { key, at: event.timeStamp } : { key: "", at: -Infinity };
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [togglePalette]);
}
