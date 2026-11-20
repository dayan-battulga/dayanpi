import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  TALK_DECODER,
  TALK_ENCODER,
  TALK_FINAL_CODES,
  TALK_PATH,
  TALK_SAMPLE_RATE,
  isSameTalking,
  listTalking,
  packTalk,
  readTalk,
  type HeardFrame,
  type TalkKind,
  type TalkTarget,
  type Talker,
} from "@/lib/talk";

const PLAYER_URL = "/assets/talk-player.js"; // web/public/assets, an AudioWorklet
const RETRY_MS = 3000;
const REFRESH_MS = 200; // how often the seats' talk chips catch up with who went quiet
const FRAME_US = 20_000;

export interface Talk {
  supported: boolean | null; // WebCodecs Opus and a mic reader, Chrome only; null while it's checking
  target: TalkTarget | null; // who your mic is for while it's on: EVERYONE or a username
  talking: Record<string, TalkKind>; // who you hear right now, and whether it's for everyone or just you
  talkTo: (target: TalkTarget) => void; // the first time, this click is what asks for the mic
  stop: () => void;
}

interface Player {
  play: (heard: HeardFrame) => void;
  close: () => void;
}

interface Mic {
  stop: () => void;
}

async function checkTalk(): Promise<boolean> {
  const present = typeof AudioEncoder !== "undefined" && typeof AudioDecoder !== "undefined" && typeof AudioWorkletNode !== "undefined" && MediaStreamTrackProcessor !== undefined;
  const [encodes, decodes] = present ? await Promise.all([AudioEncoder.isConfigSupported(TALK_ENCODER), AudioDecoder.isConfigSupported(TALK_DECODER)]) : [null, null];
  return encodes?.supported === true && decodes?.supported === true;
}

// Plays what the room says: one Opus decoder per talker into the AudioWorklet's jitter buffer, which mixes them.
// Browsers only play sound once the page has had a click (turning on the camera counts, like the peace sign's voice):
// a click before this was made is enough, and otherwise the next one wakes it.
function makePlayer(): Player {
  const context = new AudioContext({ sampleRate: TALK_SAMPLE_RATE, latencyHint: "interactive" });
  let node: AudioWorkletNode | null = null;
  void context.audioWorklet.addModule(PLAYER_URL).then(() => {
    node = new AudioWorkletNode(context, "talk-player", { numberOfInputs: 0, outputChannelCount: [1] });
    node.connect(context.destination);
  });
  const wake = () => void context.resume();
  window.addEventListener("pointerdown", wake);
  window.addEventListener("keydown", wake);
  const decoders = new Map<string, { decoder: AudioDecoder; timestamp: number }>();
  const findDecoder = (from: string) => {
    let entry = decoders.get(from);
    if (entry == null) {
      const decoder = new AudioDecoder({
        output: (data) => {
          const samples = new Float32Array(data.numberOfFrames);
          data.copyTo(samples, { planeIndex: 0, format: "f32-planar" });
          data.close();
          node?.port.postMessage({ from, samples }, [samples.buffer]);
        },
        error: () => decoders.delete(from), // a bad frame costs that talker a new decoder, nothing more
      });
      decoder.configure(TALK_DECODER);
      entry = { decoder, timestamp: 0 };
      decoders.set(from, entry);
    }
    return entry;
  };
  return {
    play: ({ from, opus }) => {
      const entry = findDecoder(from);
      entry.decoder.decode(new EncodedAudioChunk({ type: "key", timestamp: entry.timestamp, data: opus }));
      entry.timestamp += FRAME_US;
    },
    close: () => {
      window.removeEventListener("pointerdown", wake);
      window.removeEventListener("keydown", wake);
      decoders.forEach(({ decoder }) => decoder.state !== "closed" && decoder.close());
      void context.close();
    },
  };
}

// The mic, read frame by frame and encoded as 20 ms Opus frames for send. Stopping the track ends the reader, and with
// it the encoder, and takes the browser's mic light off.
async function openMic(send: (opus: Uint8Array) => void): Promise<Mic> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  const [track] = stream.getAudioTracks();
  const reader = new MediaStreamTrackProcessor!<AudioData>({ track }).readable.getReader();
  const encoder = new AudioEncoder({
    output: (chunk) => {
      const opus = new Uint8Array(chunk.byteLength);
      chunk.copyTo(opus);
      send(opus);
    },
    error: () => track.stop(),
  });
  void (async () => {
    for (let read = await reader.read(); !read.done; read = await reader.read()) {
      // The mic's own rate and channels: the encoder makes Opus of them either way, and the other side decodes to mono.
      if (encoder.state === "unconfigured") {
        encoder.configure({ ...TALK_ENCODER, sampleRate: read.value.sampleRate, numberOfChannels: read.value.numberOfChannels });
      }
      if (encoder.state === "configured") {
        encoder.encode(read.value);
      }
      read.value.close();
    }
    if (encoder.state !== "closed") {
      encoder.close();
    }
  })();
  return { stop: () => track.stop() };
}

// The room's voices, for the whole frame: one WebSocket (/api/talk) while you're signed in, so you hear the room on any
// page, and your mic, which only a click turns on (the Room page turns it off when you leave). The Pi only passes
// frames on; this end encodes, decodes and plays them.
export function useTalk(): Talk {
  const [supported, setSupported] = useState<boolean | null>(null);
  const [target, setTarget] = useState<TalkTarget | null>(null);
  const [talking, setTalking] = useState<Record<string, TalkKind>>({});
  const targetRef = useRef<TalkTarget | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const player = useRef<Player | null>(null);
  const mic = useRef<Mic | null>(null);
  const opening = useRef(false);
  const last = useRef(new Map<string, Talker>());

  useEffect(() => {
    void checkTalk().then(setSupported);
  }, []);

  useEffect(() => {
    let cleanup: (() => void) | undefined;
    if (supported === true) {
      let closed = false;
      let retry: number | undefined;
      const hear = (heard: HeardFrame) => {
        const now = performance.now() / 1000;
        last.current.set(heard.from, { kind: heard.kind, at: now });
        setTalking((current) => (current[heard.from] === heard.kind ? current : listTalking(last.current, now)));
        player.current ??= makePlayer();
        player.current.play(heard);
      };
      const open = () => {
        const opened = new WebSocket(`${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}${TALK_PATH}`);
        opened.binaryType = "arraybuffer";
        opened.onmessage = (event: MessageEvent<ArrayBuffer>) => {
          const heard = readTalk(event.data);
          if (heard != null) {
            hear(heard);
          }
        };
        opened.onclose = (event) => {
          socket.current = null;
          if (!closed && !TALK_FINAL_CODES.has(event.code)) {
            retry = window.setTimeout(open, RETRY_MS);
          }
        };
        socket.current = opened;
      };
      open();
      const refresh = window.setInterval(() => {
        const next = listTalking(last.current, performance.now() / 1000);
        setTalking((current) => (isSameTalking(current, next) ? current : next));
      }, REFRESH_MS);
      cleanup = () => {
        closed = true;
        window.clearTimeout(retry);
        window.clearInterval(refresh);
        socket.current?.close();
        player.current?.close();
        player.current = null;
      };
    }
    return cleanup;
  }, [supported]);

  const stop = useCallback(() => {
    targetRef.current = null;
    setTarget(null);
    mic.current?.stop();
    mic.current = null;
  }, []);

  const talkTo = useCallback((next: TalkTarget) => {
    targetRef.current = next;
    setTarget(next);
    player.current ??= makePlayer(); // made inside this click, so what you hear back plays too
    if (mic.current == null && !opening.current) {
      opening.current = true;
      const send = (opus: Uint8Array) => {
        if (targetRef.current != null && socket.current?.readyState === WebSocket.OPEN) {
          socket.current.send(packTalk(targetRef.current, opus));
        }
      };
      openMic(send)
        .then((opened) => {
          mic.current = opened;
          if (targetRef.current == null) {
            stop(); // stopped while the browser was still asking
          }
        })
        .catch(() => {
          targetRef.current = null;
          setTarget(null);
          toast("Couldn’t turn on your mic");
        })
        .finally(() => {
          opening.current = false;
        });
    }
  }, [stop]);

  useEffect(() => stop, [stop]);

  return { supported, target, talking, talkTo, stop };
}
