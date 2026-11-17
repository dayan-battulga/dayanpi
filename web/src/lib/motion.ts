// el.animate() restarts on every call, which a CSS animation only does when its name changes.
// offset: 0 makes a lone keyframe the starting point; the motion settles on the element's own style.
const MOTIONS = {
  tick: { duration: 450, keyframes: [{ offset: 0, opacity: 0.35, transform: "translateY(0.15em)" }] },
};
const MOTION_EASE = "cubic-bezier(0.16, 1, 0.3, 1)";

// design/SPEC.md's springs and timings, for Motion's `transition` prop.
export const SPRINGS = {
  press: { type: "spring", visualDuration: 0.2, bounce: 0.3 },
  toggle: { type: "spring", visualDuration: 0.3, bounce: 0.2 },
  layout: { type: "spring", visualDuration: 0.45, bounce: 0.1 },
  enter: { duration: 0.5, ease: [0.16, 1, 0.3, 1] },
  exit: { duration: 0.2, ease: "easeIn" },
} as const;

export type MotionName = keyof typeof MOTIONS;

// The stylesheet's reduced-motion block only reaches CSS animations, so this checks for itself.
export function replayAnimation(el: Element | null, name: MotionName): void {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (el != null && !reduced) {
    const motion = MOTIONS[name];
    el.animate(motion.keyframes, { duration: motion.duration, easing: MOTION_EASE });
  }
}
