import { readLoadLevel } from "@/lib/pi";
import type { Level } from "@/lib/types";

const BLOCK_COUNT = 20;
const MIN_CORE_SHARE = 4; // % of the bar, so an idle core still shows a sliver

interface BlocksProps {
  id: string;
  label: string;
  percent: number | null;
}

// Memory and disk: 20 blocks, filled up to the percentage.
export function Blocks({ id, label, percent }: BlocksProps) {
  const clamped = Math.max(0, Math.min(100, percent ?? 0));
  const filled = Math.round((clamped / 100) * BLOCK_COUNT);
  const level: Level | undefined = percent == null ? undefined : readLoadLevel(percent);
  return (
    <div id={id} className="blocks" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(clamped)} data-level={level}>
      {Array.from({ length: BLOCK_COUNT }, (_, index) => (
        <span key={index} className={index < filled ? "blk on" : "blk"}></span>
      ))}
    </div>
  );
}

export function CoreBars({ percents }: { percents: number[] }) {
  const described = percents.map((percent) => `${Math.round(percent)}%`).join(", ");
  return (
    <div id="cpu-cores" className="cores" role="img" aria-label={percents.length > 0 ? `Per core: ${described}` : "Per-core load not available yet"}>
      {percents.map((percent, index) => (
        <span key={index} className="core">
          <span className="core-fill" style={{ height: `${Math.max(MIN_CORE_SHARE, Math.min(100, percent))}%` }} data-level={readLoadLevel(percent)}></span>
        </span>
      ))}
    </div>
  );
}
