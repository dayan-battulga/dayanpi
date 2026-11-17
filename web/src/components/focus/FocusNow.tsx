import NumberFlow, { NumberFlowGroup } from "@number-flow/react";
import { AnimatePresence, m } from "motion/react";
import { Timeline } from "@/components/focus/Timeline";
import { MacLine } from "@/components/mac/MacLine";
import type { MacTracking } from "@/hooks/useMacTracking";
import { formatClock, formatDuration } from "@/lib/format";
import { SPRINGS } from "@/lib/motion";
import { STATE_COPY, describeProblems, isWaitingForTracker } from "@/lib/timeline";
import type { FocusStatus, Segment } from "@/lib/types";

const TWO_DIGITS = { minimumIntegerDigits: 2 };
// Minutes and seconds never show a tens digit past 5, so 59 rolls forward to 00 instead of back down through 9.
const SIXTY = { 1: { max: 5 } };

// SPEC's "swap": the old word blurs out, then the new one blurs in from a little below.
const WORD_HIDDEN = { opacity: 0, y: "0.3em", filter: "blur(4px)" };
const WORD_SHOWN = { opacity: 1, y: 0, filter: "blur(0px)", transitionEnd: { filter: "none" }, transition: { duration: 0.7, ease: SPRINGS.enter.ease } };
const WORD_LEAVING = { opacity: 0, filter: "blur(4px)", transition: SPRINGS.exit };

// Time in this state, in the state color: two rolling numbers (three past an hour) in one group, so they move together.
function StateTimer({ seconds }: { seconds: number }) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  return (
    <p className="focus-timer" role="timer" aria-label={formatClock(total)}>
      <NumberFlowGroup>
        {hours > 0 && <NumberFlow value={hours} suffix=":" aria-hidden="true" />}
        <NumberFlow value={Math.floor((total % 3600) / 60)} format={TWO_DIGITS} digits={SIXTY} aria-hidden="true" />
        <NumberFlow value={total % 60} prefix=":" format={TWO_DIGITS} digits={SIXTY} aria-hidden="true" />
      </NumberFlowGroup>
    </p>
  );
}

// formatDuration's "3h 05m" / "24m" / "40s", with each number rolling.
function DurationFlow({ seconds }: { seconds: number }) {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  let flows = <NumberFlow value={total} suffix="s" />;
  if (hours > 0) {
    flows = (
      <>
        <NumberFlow value={hours} suffix="h" /> <NumberFlow value={minutes} suffix="m" format={TWO_DIGITS} digits={SIXTY} />
      </>
    );
  } else if (total >= 60) {
    flows = <NumberFlow value={minutes} suffix="m" />;
  }
  return <span className="focus-stat">{flows}</span>;
}

// "3h 12m focused · 24m on your phone · 2 pickups": numbers in ink, words muted, and one group, since a snapshot changes
// them together. Screen readers get it as plain text.
function StatsLine({ today }: { today: FocusStatus["today"] }) {
  const pickups = today.pickups === 1 ? "pickup" : "pickups";
  return (
    <p id="focus-stats" className="focus-stats">
      <span className="sr-only">{`${formatDuration(today.working_seconds)} focused, ${formatDuration(today.phone_seconds)} on your phone, ${today.pickups} ${pickups}`}</span>
      <span aria-hidden="true">
        <NumberFlowGroup>
          <DurationFlow seconds={today.working_seconds} /> focused · <DurationFlow seconds={today.phone_seconds} /> on your phone ·{" "}
          <span className="focus-stat">
            <NumberFlow value={today.pickups} />
          </span>{" "}
          {pickups}
        </NumberFlowGroup>
      </span>
    </p>
  );
}

interface FocusNowProps {
  focus: FocusStatus | undefined;
  known: Segment[];
  loaded: boolean;
  now: number;
  midnight: number;
  receivedAt: number;
  macTracking: MacTracking;
}

// The top of the Desk, on the page with no card around it: the state word and its timer, today's timeline, the stats
// with the Mac line, and a quiet line for anything that's wrong.
export function FocusNow({ focus, known, loaded, now, midnight, receivedAt, macTracking }: FocusNowProps) {
  const state = focus?.state ?? "unknown";
  const word = (STATE_COPY[state] ?? STATE_COPY.unknown).label;
  const problems = focus == null ? "" : describeProblems(focus);
  return (
    <section className="focus rise" data-state={state} aria-label="Focus">
      <div className="focus-head">
        <h1 className="focus-word">
          <AnimatePresence mode="wait" initial={false}>
            <m.span key={word} initial={WORD_HIDDEN} animate={WORD_SHOWN} exit={WORD_LEAVING}>
              {word}
            </m.span>
          </AnimatePresence>
        </h1>
        {focus != null && <StateTimer seconds={focus.seconds_in_state + Math.max(0, now - receivedAt)} />}
      </div>
      <Timeline known={known} loaded={loaded} now={now} midnight={midnight} />
      <div className="focus-row">
        {focus != null && <StatsLine today={focus.today} />}
        <MacLine focus={focus} macTracking={macTracking} />
      </div>
      {focus != null && isWaitingForTracker(focus) && (
        <p className="focus-note">
          {/* A full page load: the tracker needs its own headers. */}
          No camera yet, so time isn't counted. <a href="/track">Open the tracker</a> in Chrome on your laptop to start.
        </p>
      )}
      {problems && <p className="focus-note">{problems}</p>}
    </section>
  );
}
