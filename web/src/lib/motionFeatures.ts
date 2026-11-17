import { domMax } from "motion/react";

// Motion's animation and layout code (layoutId needs domMax), in its own chunk that main.tsx's LazyMotion
// loads after the first paint, so /me doesn't wait on it.
export default domMax;
