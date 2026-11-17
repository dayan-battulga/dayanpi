import { LazyMotion, MotionConfig } from "motion/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "@/App";
import "@/index.css";

const loadMotionFeatures = () => import("@/lib/motionFeatures").then((module) => module.default);

// BrowserRouter runs every navigation in a transition, which is what lets Frame's <ViewTransition> animate it.
// LazyMotion + `m` keeps Motion's weight out of the first download; strict makes a stray `motion.` throw.
createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <LazyMotion features={loadMotionFeatures} strict>
      <MotionConfig reducedMotion="user">
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </MotionConfig>
    </LazyMotion>
  </StrictMode>,
);
