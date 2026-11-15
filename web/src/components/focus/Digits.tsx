import { useLayoutEffect, useRef } from "react";
import { replayAnimation } from "@/lib/motion";

// The live timer. Digits are keyed from the right, so the seconds keep their spans when an
// hour digit appears, and only the digits that changed roll.
export function Digits({ text }: { text: string }) {
  const container = useRef<HTMLSpanElement>(null);
  const previous = useRef("");
  useLayoutEffect(() => {
    const spans = Array.from(container.current?.children ?? []);
    const before = previous.current;
    Array.from(text).forEach((char, index) => {
      const beforeChar = before[before.length - (text.length - index)];
      if (char !== ":" && char !== beforeChar) {
        replayAnimation(spans[index], "roll");
      }
    });
    previous.current = text;
  }, [text]);
  return (
    <span id="focus-timer" ref={container}>
      {Array.from(text).map((char, index) => (
        <span key={text.length - index} className={char === ":" ? "digit-sep" : "digit"}>
          {char}
        </span>
      ))}
    </span>
  );
}
