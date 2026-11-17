import { useEffect, useRef, useState } from "react";
import type { Spoken } from "@/lib/types";

export interface PeaceVoice {
  playing: boolean; // the audio element says it's playing (its own playing and ended events)
  blocked: boolean; // the browser wouldn't play it without a click on this page; play() is that click
  play: () => void;
}

// The peace sign's clip, when the desk speaks through this computer: the Pi makes it with Piper and keeps it in memory
// until one page fetches it (GET /api/voice/clip, once), so every page that sees spoken.clip for a new message tries,
// and the first one plays it. A click anywhere on the page earlier lets the browser play it; otherwise the pill shows
// a play button.
export function usePeaceVoice(spoken: Spoken | null | undefined): PeaceVoice {
  const [playing, setPlaying] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  const fetchedAt = useRef<number | null>(null);
  const at = spoken?.at ?? null;
  const hasClip = spoken?.clip === true;

  useEffect(() => {
    if (hasClip && at !== null && fetchedAt.current !== at) {
      fetchedAt.current = at;
      setBlocked(false);
      void fetch("/api/voice/clip", { cache: "no-store" }).then(async (response) => {
        if (response.ok) {
          const player = audio.current ?? new Audio();
          audio.current = player;
          if (player.src) {
            URL.revokeObjectURL(player.src);
          }
          player.onplaying = () => {
            setPlaying(true);
            setBlocked(false);
          };
          player.onended = player.onpause = player.onerror = () => setPlaying(false);
          player.src = URL.createObjectURL(await response.blob());
          player.play().catch((error: unknown) => setBlocked(error instanceof DOMException && error.name === "NotAllowedError"));
        }
      });
    }
  }, [at, hasClip]);

  useEffect(() => {
    return () => {
      audio.current?.pause();
      if (audio.current?.src) {
        URL.revokeObjectURL(audio.current.src);
      }
    };
  }, []);

  const play = () => {
    void audio.current?.play().catch(() => setBlocked(true));
  };
  return { playing, blocked, play };
}
