import { useState } from "react";
import { Blocks, CoreBars } from "@/components/pi/Meters";
import { riseDelay } from "@/components/shared/rise";
import { TickText } from "@/components/shared/TickText";
import { Switch } from "@/components/ui/switch";
import { formatBits, formatUptime } from "@/lib/format";
import { GAUGE_MAX_C, GAUGE_MIN_C, TEMP_CRITICAL_C, TEMP_ELEVATED_C, describePi, describePower, readLevel, readLoadLevel } from "@/lib/pi";
import type { FocusStatus, Snapshot } from "@/lib/types";

function describeVoice(voice: FocusStatus["voice"] | undefined): string {
  let text = "off";
  if (voice != null && voice.enabled) {
    text = voice.backend;
  } else if (voice != null && voice.problem) {
    text = "error";
  }
  return text;
}

// A snapshot built just before the switch flipped can still arrive after the reply, so the reply wins for a moment.
const SWITCH_HOLD_S = 2.5;

async function sendMacTracking(enabled: boolean): Promise<boolean> {
  let saved = false;
  try {
    const response = await fetch("/api/mac/tracking", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    saved = response.ok;
  } catch {
    saved = false;
  }
  return saved;
}

function describeMac(focus: FocusStatus | undefined, tracking: boolean): string {
  const text =
    focus == null ? "--" : !tracking ? "Paused" : focus.app && focus.site ? `${focus.app} · ${focus.site}` : focus.app || "—";
  return text;
}

export function PiSection({ stats, now }: { stats: Snapshot | null; now: number }) {
  // The switch flips right away; a failed POST drops the hold and it goes back to what the Pi says.
  const [held, setHeld] = useState<{ enabled: boolean; until: number } | null>(null);
  const power = stats == null ? null : describePower(stats.throttle);
  const summary = stats == null || power == null ? null : describePi(stats, power);
  const temp = stats?.temperature_celsius;
  const tempLevel = temp == null ? "nominal" : readLevel(temp, TEMP_ELEVATED_C, TEMP_CRITICAL_C);
  const gaugeShare = temp == null ? null : Math.max(0, Math.min(100, ((temp - GAUGE_MIN_C) / (GAUGE_MAX_C - GAUGE_MIN_C)) * 100));
  const rates = stats?.rates ?? null;
  const cores = rates?.core_percents ?? [];
  const memory = stats?.memory;
  const disk = stats?.disk;
  const focus = stats?.focus;
  const tracking = held != null && now < held.until ? held.enabled : (focus?.mac_tracking ?? true);
  const flipTracking = async (enabled: boolean) => {
    setHeld({ enabled, until: Infinity });
    const saved = await sendMacTracking(enabled);
    setHeld(saved ? { enabled, until: Date.now() / 1000 + SWITCH_HOLD_S } : null);
  };

  return (
    <section id="pi" className="pi rise" style={riseDelay(5)} aria-labelledby="pi-summary">
      <div className="pi-head">
        <div>
          <span className="label">Raspberry Pi 5</span>
          <TickText as="h2" id="pi-summary" className="pi-summary" data-level={summary?.level} value={summary?.text ?? "Connecting…"} />
        </div>
        <span className="mono muted small">updates every second</span>
      </div>

      <div className="tiles">
        <div className="card tile">
          <span className="label">Temp</span>
          <div className="gauge">
            <svg viewBox="0 0 120 92" aria-hidden="true">
              <path className="gauge-track" pathLength="100" d="M20.16 83 A46 46 0 1 1 99.84 83"></path>
              <path
                id="temp-arc"
                className="gauge-value"
                pathLength="100"
                d="M20.16 83 A46 46 0 1 1 99.84 83"
                data-level={tempLevel}
                style={gaugeShare == null ? undefined : { strokeDasharray: `${gaugeShare.toFixed(1)} 100` }}
              ></path>
            </svg>
            <div className="gauge-text">
              <span className="mono gauge-number">
                <TickText id="temp" data-level={tempLevel} value={temp == null ? "--" : temp.toFixed(1)} />°
              </span>
              <span className="muted small">throttles near 80°</span>
            </div>
          </div>
        </div>

        <div className="card tile">
          <div className="tile-head">
            <span className="label">CPU</span>
            <span id="cpu-cores-label" className="mono muted small">
              {cores.length > 0 ? `${cores.length} cores` : "all cores"}
            </span>
          </div>
          <div className="cpu-row">
            <p className="mono tile-number">
              <TickText id="cpu" data-level={rates == null ? "nominal" : readLoadLevel(rates.cpu_percent)} value={rates == null ? "--" : Math.round(rates.cpu_percent)} />
              <span className="unit"> %</span>
            </p>
            <CoreBars percents={cores} />
          </div>
          <p className="muted small tile-note">one bar per core, live</p>
        </div>

        <div className="card tile">
          <div className="tile-head">
            <span className="label">Memory</span>
            <TickText
              id="mem-detail"
              className="mono muted small"
              value={memory == null ? "--" : `${((memory.total_mb - memory.available_mb) / 1024).toFixed(1)} / ${(memory.total_mb / 1024).toFixed(1)} GB`}
            />
          </div>
          <p className="mono tile-number">
            <TickText id="mem-percent" value={memory == null ? "--" : Math.round(memory.percent_used)} />
            <span className="unit"> %</span>
          </p>
          <Blocks id="mem-blocks" label="Memory used" percent={memory?.percent_used ?? null} />
        </div>

        <div className="card tile">
          <div className="tile-head">
            <span className="label">Disk</span>
            <TickText id="disk-detail" className="mono muted small" value={disk == null ? "--" : `${disk.free_gb.toFixed(1)} GB free`} />
          </div>
          <p className="mono tile-number">
            <TickText id="disk-percent" value={disk == null ? "--" : Math.round(disk.percent_used)} />
            <span className="unit"> %</span>
          </p>
          <Blocks id="disk-blocks" label="Disk used" percent={disk?.percent_used ?? null} />
        </div>
      </div>

      <div className="card status-bar">
        <dl>
          <div>
            <dt className="label">Network</dt>
            <TickText as="dd" id="net" className="mono" value={rates == null ? "--" : `↓ ${formatBits(rates.rx_kbps)} · ↑ ${formatBits(rates.tx_kbps)}`} />
          </div>
          <div>
            <dt className="label">Uptime</dt>
            <TickText as="dd" id="uptime" className="mono" value={stats == null ? "--" : formatUptime(stats.uptime_seconds)} />
          </div>
          <div>
            <dt className="label">Power</dt>
            <TickText as="dd" id="power" className="mono" data-level={power?.level ?? "nominal"} value={power?.text ?? "--"} />
          </div>
          <div>
            <dt className="label">Voice</dt>
            <dd id="voice" className="mono">
              {focus == null ? "--" : describeVoice(focus.voice)}
            </dd>
          </div>
          <div>
            <dt className="label">Mac</dt>
            <dd className="mono flex items-center gap-2">
              {focus != null && <Switch checked={tracking} onCheckedChange={flipTracking} aria-label="Mac tracking" />}
              <span id="mac">{describeMac(focus, tracking)}</span>
            </dd>
          </div>
          <div>
            <dt className="label">Sign</dt>
            <dd id="sign-mode" className="mono">
              {focus == null ? "--" : (focus.sign?.mode ?? "off")}
            </dd>
          </div>
        </dl>
      </div>
    </section>
  );
}
