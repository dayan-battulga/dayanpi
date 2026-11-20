// Smooth video on the seats (focus/smooth_video.py has the Pi's half): who sends what to whom, and how much.
import type { FocusStatus } from "@/lib/types";

export const MAX_PEERS = 3; // a full room is four, so everyone sends to three at most
export const VIDEO_MAX_BITRATE = 600_000;
export const VIDEO_MAX_FPS = 30;
export const VIDEO_WIDTH = 640;
export const VIDEO_HEIGHT = 360;
export const RTC_REFRESH_MS = 30 * 60 * 1000; // TURN credentials last hours; a new connection never gets stale ones
export const RETRY_MS = 15_000; // a pair that couldn't connect stays on pictures this long before it tries again
export const CONNECT_TIMEOUT_MS = 20_000; // a connection not up by then counts as failed (a signal got lost on the way)
export const HELLO_AGAIN_MS = 15_000; // the answering side asks again this often until an offer comes

export interface RtcReply {
  smooth_video: boolean;
  ice_servers: RTCIceServer[]; // empty while it's off: nothing outside is ever in the page then
}

// Hide still means hidden: your camera goes out only while smooth video is on, the camera is on in this browser, your
// room picture is this browser's (not the Pi's camera), you share video, and you're working or on the phone. Anything
// else sends nothing, and the others' seats fall back to your picture, or your initial.
export function findSendingTrack(focus: FocusStatus | undefined, preview: MediaStream | null, enabled: boolean): MediaStreamTrack | null {
  const allowed = enabled && focus?.picture_source === "browser" && focus.sharing?.video === true && (focus.state === "working" || focus.state === "phone");
  const track = allowed ? (preview?.getVideoTracks()[0] ?? null) : null;
  return track;
}

// At most 640x360, 30 fps and about 600 kbps per person; WebRTC steps down from there on a weak connection. The track
// itself is never touched, so the frames the models check stay as they are.
export function capEncoding(track: MediaStreamTrack): RTCRtpEncodingParameters {
  const { width = VIDEO_WIDTH, height = VIDEO_HEIGHT } = track.getSettings();
  const encoding = { maxBitrate: VIDEO_MAX_BITRATE, maxFramerate: VIDEO_MAX_FPS, scaleResolutionDownBy: Math.max(1, width / VIDEO_WIDTH, height / VIDEO_HEIGHT) };
  return encoding;
}

// One side of each pair makes the offer, the same one every time, so two browsers never both do.
export function isOfferer(me: string, peer: string): boolean {
  const offers = me < peer;
  return offers;
}
