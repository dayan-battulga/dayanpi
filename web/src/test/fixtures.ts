import type { FocusStatus, Snapshot, Todos } from "@/lib/types";

export const TODOS: Todos = {
  current: "a1",
  open: [
    { id: "a1", text: "finish the report", seconds: 754, done_at: null },
    { id: "b2", text: "reply to emails", seconds: 0, done_at: null },
  ],
  done: [],
};

export function makeFocus(changes: Partial<FocusStatus> = {}): FocusStatus {
  const now = Date.now() / 1000;
  const focus: FocusStatus = {
    state: "working",
    since: now - 125,
    seconds_in_state: 125,
    today: { working_seconds: 3900, phone_seconds: 300, pickups: 3, longest_streak_seconds: 2400, first_seen: now - 7200 },
    app: "Code",
    camera_ok: true,
    last_check: { person: 0.92, phone: 0.04, elapsed_ms: 186 },
    enabled: true,
    side_camera: false,
    overlay: {
      at: now,
      age_s: 0.4,
      frame_width: 768,
      frame_height: 432,
      boxes: [{ kind: "person", label: "person", confidence: 0.92, x: 0.2, y: 0.1, width: 0.5, height: 0.8 }],
    },
    side_overlay: null,
    voice: { enabled: false, backend: "off", problem: null },
    todos: TODOS,
    ...changes,
  };
  return focus;
}

export function makeSnapshot(focus: FocusStatus = makeFocus()): Snapshot {
  const snapshot: Snapshot = {
    temperature_celsius: 48.2,
    uptime_seconds: 3 * 86400 + 3600,
    memory: { total_mb: 8000, available_mb: 5000, percent_used: 37.5 },
    disk: { percent_used: 40, free_gb: 20.4 },
    throttle: { is_undervoltage: false, is_frequency_capped: false, is_throttled: false, has_undervoltage_occured: false, has_throttling_occured: false },
    rates: { cpu_percent: 23.4, core_percents: [20, 30, 25, 18], rx_kbps: 120, tx_kbps: 1500 },
    focus,
  };
  return snapshot;
}
