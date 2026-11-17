import NumberFlow, { NumberFlowGroup } from "@number-flow/react";
import type { ReactNode } from "react";
import { riseDelay } from "@/components/shared/rise";
import { TEMP_CRITICAL_C, TEMP_ELEVATED_C, readLevel, readUptime } from "@/lib/pi";
import type { FocusStatus, Level, PiStats } from "@/lib/types";

const ONE_DECIMAL = { minimumFractionDigits: 1, maximumFractionDigits: 1 };

interface StatProps {
  label: string;
  text: string; // the plain copy, for screen readers (the rolling digits are hidden from them)
  share: number | null; // how full its bar is, in %; null for no bar
  tone?: Level; // the temperature's bar turns warm, then hot
  children: ReactNode;
}

function Stat({ label, text, share, tone, children }: StatProps) {
  return (
    <div className="pi-stat">
      <dt>{label}</dt>
      <dd>
        <span className="sr-only">{text}</span>
        <span className="pi-value" aria-hidden="true">
          {children}
        </span>
        <span className="pi-bar" data-empty={share == null || undefined}>
          {share != null && <span style={{ width: `${Math.max(0, Math.min(100, share))}%` }} data-tone={tone} />}
        </span>
      </dd>
    </div>
  );
}

// /pi's "The Pi": temperature, CPU, memory and uptime, each rolling to its new number, and the undervoltage
// warning while it's happening.
export function PiSection({ stats, focus }: { stats: PiStats | null; focus: FocusStatus | undefined }) {
  const temp = stats == null ? null : Math.round(stats.temperature_celsius);
  const cpu = stats?.rates == null ? null : Math.round(stats.rates.cpu_percent);
  const memory = stats?.memory ?? null;
  const usedGb = memory == null ? null : Math.round(((memory.total_mb - memory.available_mb) / 1024) * 10) / 10;
  const totalGb = memory == null ? null : Math.round(memory.total_mb / 1024);
  const uptime = stats == null ? null : readUptime(stats.uptime_seconds);
  const foot = ["YOLO26n", focus?.enabled === false ? "detector off" : "one check a second", focus?.side_camera ? "both cameras" : "one camera"].join(" · ");

  return (
    <section className="pi rise" style={riseDelay(1)} aria-labelledby="pi-title">
      <h2 id="pi-title" className="section-title">
        The Pi
      </h2>
      {stats?.throttle.is_undervoltage && (
        <p role="alert" className="pi-alert">
          Undervoltage: the power supply can’t keep up, so the Pi may slow down or freeze.
        </p>
      )}
      <NumberFlowGroup>
        <dl className="pi-stats">
          <Stat label="Temperature" text={temp == null ? "—" : `${temp}°C`} share={temp} tone={temp == null ? undefined : readLevel(temp, TEMP_ELEVATED_C, TEMP_CRITICAL_C)}>
            {temp == null ? "—" : <NumberFlow value={temp} suffix="°C" />}
          </Stat>
          <Stat label="CPU" text={cpu == null ? "—" : `${cpu}%`} share={cpu}>
            {cpu == null ? "—" : <NumberFlow value={cpu} suffix="%" />}
          </Stat>
          <Stat label={totalGb == null ? "Memory" : `Memory of ${totalGb} GB`} text={usedGb == null ? "—" : `${usedGb.toFixed(1)} GB`} share={memory?.percent_used ?? null}>
            {usedGb == null ? "—" : <NumberFlow value={usedGb} format={ONE_DECIMAL} suffix=" GB" />}
          </Stat>
          <Stat label="Up for" text={uptime == null ? "—" : `${uptime.first}${uptime.firstUnit} ${uptime.second}${uptime.secondUnit}`} share={null}>
            {uptime == null ? (
              "—"
            ) : (
              <>
                <NumberFlow value={uptime.first} suffix={uptime.firstUnit} /> <NumberFlow value={uptime.second} suffix={uptime.secondUnit} />
              </>
            )}
          </Stat>
        </dl>
      </NumberFlowGroup>
      <p className="pi-foot">{foot}</p>
    </section>
  );
}
