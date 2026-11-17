// design/SPEC.md's springs and timings, for Motion's `transition` prop.
export const SPRINGS = {
  press: { type: "spring", visualDuration: 0.2, bounce: 0.3 },
  toggle: { type: "spring", visualDuration: 0.3, bounce: 0.2 },
  layout: { type: "spring", visualDuration: 0.45, bounce: 0.1 },
  enter: { duration: 0.5, ease: [0.16, 1, 0.3, 1] },
  exit: { duration: 0.2, ease: "easeIn" },
} as const;
