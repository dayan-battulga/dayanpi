export type FocusState = "working" | "phone" | "away" | "unknown";
export type Level = "nominal" | "elevated" | "critical";
export type Connection = "connected" | "reconnecting" | "disconnected";

export interface Segment {
  state: FocusState;
  start: number;
  end: number | null;
}

export interface OverlayBox {
  kind: string;
  label: string;
  confidence: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

// One COCO keypoint: x and y as 0-1 fractions of the frame, then the model's confidence.
export type PosePoint = [number, number, number];

export interface Overlay {
  at: number;
  age_s: number;
  frame_width: number;
  frame_height: number;
  boxes: OverlayBox[];
  pose?: PosePoint[] | null; // only with the pose model loaded (front feed); null when nobody's clear
}

export interface TodoItem {
  id: string;
  text: string;
  seconds: number;
  done_at: number | null;
}

export interface Todos {
  current: string | null;
  open: TodoItem[];
  done: TodoItem[];
}

export interface CheckSummary {
  person: number;
  phone: number;
  elapsed_ms: number;
}

export interface FocusStatus {
  state: FocusState;
  since: number;
  seconds_in_state: number;
  today: {
    working_seconds: number;
    phone_seconds: number;
    pickups: number;
    longest_streak_seconds: number;
    first_seen: number | null;
  };
  block: { active: boolean };
  app: string | null;
  site?: string | null; // the browser tab's host name, when the Mac's front app is a browser that says
  mac_tracking?: boolean; // the dashboard's switch for the Mac helper
  camera_ok: boolean;
  last_check: CheckSummary | null;
  enabled: boolean;
  side_camera: boolean;
  overlay: Overlay | null;
  side_overlay: Overlay | null;
  voice: { enabled: boolean; backend: string; problem: string | null } | null;
  sign?: { mode: string; page: string | null; version: number | null };
  todos?: Todos;
  gesture?: { name: string; age_s: number } | null; // the last arm gesture or hand sign that fired
}

export interface Throttle {
  is_undervoltage: boolean;
  is_frequency_capped: boolean;
  is_throttled: boolean;
  has_undervoltage_occured: boolean;
  has_throttling_occured: boolean;
}

export interface Snapshot {
  temperature_celsius: number;
  uptime_seconds: number;
  memory: { total_mb: number; available_mb: number; percent_used: number };
  disk: { percent_used: number; free_gb: number };
  throttle: Throttle;
  rates: { cpu_percent: number; core_percents?: number[]; rx_kbps: number; tx_kbps: number } | null;
  focus?: FocusStatus;
}

// The numbers in a day page's frontmatter; a page edited by hand may have dropped some.
export interface DayNumbers {
  focus_minutes?: number;
  phone_minutes?: number;
  away_minutes?: number;
  pickups?: number;
  best_streak_minutes?: number;
  blocks?: number;
  todos_done?: number;
}

export interface MonthDays {
  month: string;
  today: string;
  days: Record<string, DayNumbers>;
}

export interface DayPageReply {
  day: string;
  today: boolean;
  markdown: string;
}
