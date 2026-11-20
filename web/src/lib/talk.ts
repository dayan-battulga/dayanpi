// Talking in the room: the messages on /api/talk (focus/talk.py has the Pi's half) and who's talking right now.

// Who your mic is for: EVERYONE, or the one username (no username is empty, and "everyone" could be one).
export type TalkTarget = string;
export type TalkKind = "everyone" | "you"; // what a frame you hear was for

export const EVERYONE = "";
export const TALK_PATH = "/api/talk";
export const TALK_SAMPLE_RATE = 48_000; // Opus's own; the page's AudioContext runs at it so nothing resamples twice
export const TALK_ENCODER: AudioEncoderConfig = { codec: "opus", sampleRate: TALK_SAMPLE_RATE, numberOfChannels: 1, bitrate: 24_000, opus: { frameDuration: 20_000 } };
export const TALK_DECODER: AudioDecoderConfig = { codec: "opus", sampleRate: TALK_SAMPLE_RATE, numberOfChannels: 1 };
export const TALKING_FOR_S = 0.6; // someone's chip stays this long after their last frame
// The Pi closes with these when trying again won't help: signed out, a malformed message, a newer tab took over.
export const TALK_FINAL_CODES = new Set([1007, 1008, 4001]);

const TO_YOU = 1;

// What goes up: [target length][target, empty for everyone][one Opus frame].
export function packTalk(target: TalkTarget, opus: Uint8Array): Uint8Array<ArrayBuffer> {
  const name = new TextEncoder().encode(target);
  const packed = new Uint8Array(1 + name.length + opus.length);
  packed[0] = name.length;
  packed.set(name, 1);
  packed.set(opus, 1 + name.length);
  return packed;
}

export interface HeardFrame {
  from: string;
  kind: TalkKind;
  opus: Uint8Array;
}

// What comes down: [kind][sender length][sender][one Opus frame]; null for anything shorter.
export function readTalk(message: ArrayBuffer): HeardFrame | null {
  const bytes = new Uint8Array(message);
  const nameEnd = 2 + (bytes[1] ?? 0);
  const heard =
    bytes.length > nameEnd
      ? { from: new TextDecoder().decode(bytes.subarray(2, nameEnd)), kind: bytes[0] === TO_YOU ? ("you" as const) : ("everyone" as const), opus: bytes.subarray(nameEnd) }
      : null;
  return heard;
}

export interface Talker {
  kind: TalkKind;
  at: number; // seconds, performance.now's clock
}

// Who's talking, as the seats show it: each sender whose last frame came within TALKING_FOR_S, and what it was for.
export function listTalking(last: Map<string, Talker>, now: number): Record<string, TalkKind> {
  const talking = Object.fromEntries([...last].filter(([, talker]) => now - talker.at <= TALKING_FOR_S).map(([from, talker]) => [from, talker.kind]));
  return talking;
}

// So the room redraws when someone starts or stops, not fifty times a second.
export function isSameTalking(first: Record<string, TalkKind>, second: Record<string, TalkKind>): boolean {
  const keys = Object.keys(first);
  const same = keys.length === Object.keys(second).length && keys.every((key) => first[key] === second[key]);
  return same;
}
