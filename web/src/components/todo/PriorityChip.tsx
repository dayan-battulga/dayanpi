import { ChevronDown } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import { PRIORITIES } from "@/lib/todos";
import type { Priority } from "@/lib/types";

interface PriorityChipProps {
  priority: Priority;
  text: string; // the to-do's, so a screen reader knows whose priority it is
  onPick: (priority: Priority) => void;
}

// A to-do's priority (RoomV2's chip): a colored dot and "High ▾", or an outlined "Priority ▾" with none. It opens a small
// menu of the four with a check on the current one (Radix, so arrows, Enter and Esc work).
export function PriorityChip({ priority, text, onPick }: PriorityChipProps) {
  const picked = PRIORITIES.find((entry) => entry.value === priority) ?? PRIORITIES[PRIORITIES.length - 1];
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger className="priority-chip" data-priority={priority} aria-label={`Priority of ${text}: ${picked.label}`}>
        <span className="priority-dot" aria-hidden="true" />
        <span className="priority-chip-label">{priority === "none" ? "Priority" : picked.label}</span>
        <ChevronDown size={10} strokeWidth={2.4} aria-hidden="true" />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6} className="priority-menu">
          <DropdownMenu.RadioGroup value={priority} onValueChange={(value) => onPick(value as Priority)}>
            {PRIORITIES.map((entry) => (
              <DropdownMenu.RadioItem key={entry.value} value={entry.value} className="priority-item" data-priority={entry.value}>
                <span className="priority-item-label">
                  <span className="priority-dot" aria-hidden="true" />
                  {entry.label}
                </span>
                <DropdownMenu.ItemIndicator className="priority-check" aria-hidden="true">
                  ✓
                </DropdownMenu.ItemIndicator>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
