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

export interface Spoken {
  text: string;
  at: number;
  age_s: number;
  speaking: boolean;
  clip?: boolean;
  kind?: "peace" | "nudge"; // a nudge plays the same way, and shows as a toast instead of the pill
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
  side_camera_running?: boolean; // the side camera is there and still sending frames (mine only)
  camera_access?: CameraAccess;
  camera_source?: "pi" | "browser"; // where the desk's checks come from: the Pi's cameras (mine only) or /track
  picture_source?: "pi" | "browser"; // where the seat's picture comes from: a Pi camera (mine only) or this browser
  pi_camera?: "front" | "side"; // which Pi camera, when it's the Pi's: front until picked
  camera_paused?: boolean; // /track's Pause, until its next reading
  overlay: Overlay | null;
  side_overlay: Overlay | null;
  voice: { enabled: boolean; backend: string; problem: string | null } | null;
  todos?: Todos;
  gesture?: { name: string; age_s: number } | null; // the last hand sign that fired
  // What the peace sign said last; speaking: the Pi's speaker is still saying it; clip: a clip waits for this page to play.
  spoken?: Spoken | null;
  bedtime?: string; // "HH:MM", the desk's own (Settings → Voice and bedtime)
  voice_output?: "pi" | "computer"; // where the peace sign speaks
  sharing?: Sharing; // what the room sees of this desk (Settings → Share with the room)
  goal_minutes?: number | null; // your daily focus goal (Settings → Profile), null when off; never anyone else's
}

// Settings → Share with the room. Status (the state and its timer) always shows, so it isn't a switch.
// The colors anyone can pick for their lamp while focused (focus/sharing.py's LAMP_COLORS, dashboard.css's --lamp-*).
export type LampColor = "teal" | "green" | "sky" | "yellow" | "pink" | "white";

export interface Sharing {
  focus: boolean;
  todos: boolean;
  history: boolean;
  apps: boolean;
  sites: boolean;
  video: boolean;
  nudges: boolean; // whether others may nudge you
  lamp: LampColor; // your lamp's color while focused, which everyone sees
}

export type SharedPart = "focus" | "todos" | "apps" | "sites" | "video" | "history";

export type SeatState = FocusState | "offline";

// One person as the room sees them, built on the Pi (focus/sharing.py). A part they don't share is missing.
export interface Seat {
  username: string;
  name: string;
  here: boolean;
  state: SeatState;
  seconds_in_state: number | null; // null while offline
  shares: SharedPart[]; // what they show, so a page can tell a piece turned on or off
  hidden: boolean; // someone tidied this offline seat out of the Room (POST /api/room/hide); false again once they're here
  lamp: LampColor; // their lamp's color while focused; always sent, like their name
  focus_seconds?: number;
  todos?: { current: string | null; current_seconds: number | null; done: number; total: number };
  app?: string | null;
  site?: string | null;
  nudge?: { wait_s: number; age_s: number | null }; // only while they take nudges
  picture?: { at: number } | null; // while they share video: a fresh picture to fetch (/api/people/<username>/picture), or none
}

// Someone's desk (/api/people/<username>): their seat and each piece they share. A piece they don't share is missing.
export interface TheirDesk extends Seat {
  here_since: number | null; // when the camera first saw them today, while they're here; status, so always there
  today?: { working_seconds: number; phone_seconds: number; pickups: number; segments: Segment[] };
  todo_list?: Todos;
  apps?: { app: string; total_seconds: number }[];
  app_youtube?: Record<string, number>;
  sites?: { site: string; seconds: number }[];
  history?: { month: string; today: string; joined_at: number; days: Record<string, number>; total_minutes: number };
  video?: true;
}

export interface Room {
  seats: Seat[]; // oldest account first; lib/account's ROOM_SIZE is the most there can be
}

export interface PiStats {
  temperature_celsius: number;
  uptime_seconds: number;
  memory: { total_mb: number; available_mb: number; percent_used: number };
  throttle: { is_undervoltage: boolean };
  rates: { cpu_percent: number } | null;
}

// The owner's stream carries the Pi's numbers; a member's carries only "focus" and "room".
export interface Snapshot extends Partial<PiStats> {
  focus?: FocusStatus;
  room?: Room | null; // null for the first second after the Pi starts
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
  studied_with?: StudiedWith[]; // most minutes first
}

// Someone you were focused at the same time as for 5+ minutes that day, if they share focus time and history.
export interface StudiedWith {
  username: string;
  name: string;
  lamp: LampColor;
  minutes: number; // the overlap, not their total
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
