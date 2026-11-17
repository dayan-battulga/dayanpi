export type FocusState = "working" | "phone" | "away" | "unknown";
export type Level = "nominal" | "elevated" | "critical";
export type Connection = "connected" | "reconnecting" | "disconnected";
// "open" (or missing, from an older Pi): the feeds work. Otherwise /video answers 404 for this viewer.
export type CameraAccess = "open" | "tailscale_only" | "owner_only";
export type RecordId = number | string;

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

export interface Overlay {
  at: number;
  age_s: number;
  frame_width: number;
  frame_height: number;
  boxes: OverlayBox[];
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
  app: string | null;
  site?: string | null; // the browser tab's host name, when the Mac's front app is a browser that says
  mac_tracking?: boolean; // the dashboard's switch for the Mac helper
  camera_ok: boolean;
  last_check: CheckSummary | null;
  enabled: boolean;
  side_camera: boolean;
  camera_access?: CameraAccess;
  camera_source?: "pi" | "browser"; // where the desk's checks come from: the Pi's cameras (mine only) or /track
  camera_paused?: boolean; // /track's Pause, until its next reading
  overlay: Overlay | null;
  side_overlay: Overlay | null;
  voice: { enabled: boolean; backend: string; problem: string | null } | null;
  todos?: Todos;
  gesture?: { name: string; age_s: number } | null; // the last hand sign that fired
  spoken?: { text: string; at: number; age_s: number; speaking: boolean } | null; // what the peace sign said last, and whether the voice still is
}

export interface Throttle {
  is_undervoltage: boolean;
  is_frequency_capped: boolean;
  is_throttled: boolean;
  has_undervoltage_occured: boolean;
  has_throttling_occured: boolean;
}

export interface PiStats {
  temperature_celsius: number;
  uptime_seconds: number;
  memory: { total_mb: number; available_mb: number; percent_used: number };
  disk: { percent_used: number; free_gb: number };
  throttle: Throttle;
  rates: { cpu_percent: number; core_percents?: number[]; rx_kbps: number; tx_kbps: number } | null;
}

// The owner's stream carries the Pi's numbers; a member's carries only "focus".
export interface Snapshot extends Partial<PiStats> {
  focus?: FocusStatus;
}

export interface User {
  id: RecordId;
  username: string;
  display_name: string;
  role: "owner" | "member";
}

export interface ApiToken {
  id: RecordId;
  name: string;
  created_at: number;
  last_used_at: number | null;
}

export interface Invite {
  id: RecordId;
  created_at: number;
  expires_at: number;
}

export interface Account {
  id: RecordId;
  username: string;
  display_name: string;
  role: "owner" | "member";
  created_at: number;
}

// The numbers in a day page's frontmatter; a page edited by hand may have dropped some.
export interface DayNumbers {
  focus_minutes?: number;
  phone_minutes?: number;
  away_minutes?: number;
  pickups?: number;
  best_streak_minutes?: number;
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

export type AppsRange = "today" | "week";

// Only an app that had a site in the range carries the two site fields; "Other apps" never does.
export interface AppUsage {
  app: string;
  total_seconds: number;
  youtube_seconds?: number;
  other_sites_seconds?: number;
}

export interface AppsReply {
  range: AppsRange;
  apps: AppUsage[];
}
