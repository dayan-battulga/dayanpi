import type { HTMLAttributes, Ref } from "react";
import { useReplayOnChange } from "@/hooks/useReplayOnChange";

interface TickTextProps extends HTMLAttributes<HTMLElement> {
  value: string | number;
  as?: "span" | "dd" | "h2";
}

// A number or short text that nudges in each time it changes, like the old setText().
export function TickText({ value, as: Tag = "span", ...props }: TickTextProps) {
  const ref = useReplayOnChange<HTMLElement>(String(value), "tick");
  return (
    <Tag ref={ref as Ref<never>} {...props}>
      {value}
    </Tag>
  );
}
