import { m } from "motion/react";
import { Switch as SwitchPrimitive } from "radix-ui";
import { SPRINGS } from "@/lib/motion";

interface SwitchProps {
  label: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}

const THUMB_TRAVEL_PX = 18; // the 46 px track less the 22 px thumb and 3 px either side

// Radix's switch in the mockups' look: the thumb slides on SPEC's "toggle" spring.
export function Switch({ label, checked, onCheckedChange }: SwitchProps) {
  return (
    <SwitchPrimitive.Root className="switch" aria-label={label} checked={checked} onCheckedChange={onCheckedChange}>
      <span className="switch-track">
        <SwitchPrimitive.Thumb asChild>
          <m.span className="switch-thumb" initial={false} animate={{ x: checked ? THUMB_TRAVEL_PX : 0 }} transition={SPRINGS.toggle} />
        </SwitchPrimitive.Thumb>
      </span>
    </SwitchPrimitive.Root>
  );
}
