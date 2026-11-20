import { useEffect, useRef, useState, type ReactNode } from "react";

const FRAMES_KEPT = 2; // the one fading in, over the one it replaces

interface Frame {
  at: number;
  url: string;
}

// Someone's once-a-second picture, from /api/people/<username>/picture. Each new frame (a new `at` on the stream) fades
// in over the last one, so it reads as a calm live photo. Mount it only while the seat says there's a picture: it
// fetches nothing else, and unmounting lets go of every frame. mirrored: it's you, so you see yourself as in a mirror;
// only on screen, since the Pi's picture itself (what everyone else gets) is the true way round.
export function SeatPicture({ username, at, mirrored = false }: { username: string; at: number; mirrored?: boolean }) {
  const [frames, setFrames] = useState<Frame[]>([]);
  const held = useRef<Frame[]>([]);

  useEffect(() => {
    let current = true;
    void fetch(`/api/people/${encodeURIComponent(username)}/picture?at=${at}`, { cache: "no-store" })
      .then(async (response) => {
        if (current && response.ok) {
          const frame = { at, url: URL.createObjectURL(await response.blob()) };
          setFrames((before) => [...before.slice(1 - FRAMES_KEPT), frame]);
        }
      })
      .catch(() => {
        // Gone (hidden, away, too old) or offline for a moment: the last frame stays until the seat says otherwise.
      });
    return () => {
      current = false;
    };
  }, [username, at]);

  // Frees each frame once it's off the stack, and all of them when the picture goes.
  useEffect(() => {
    held.current.filter((frame) => !frames.includes(frame)).forEach((frame) => URL.revokeObjectURL(frame.url));
    held.current = frames;
  }, [frames]);
  useEffect(() => () => held.current.forEach((frame) => URL.revokeObjectURL(frame.url)), []);

  return (
    <span className="seat-picture" aria-hidden="true">
      {frames.map((frame) => (
        <img key={frame.at} className={mirrored ? "seat-picture-frame is-mirrored" : "seat-picture-frame"} src={frame.url} alt="" />
      ))}
    </span>
  );
}

// Someone's smooth video (hooks/useSmoothVideo): their camera, straight from their browser, fading in over their
// picture once it plays and back to the picture whenever it stops (their camera dropped, the connection's gone).
export function SeatVideo({ stream, children }: { stream: MediaStream; children: ReactNode }) {
  const video = useRef<HTMLVideoElement | null>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    const element = video.current;
    const [track] = stream.getVideoTracks();
    const check = () => setPlaying(track != null && !track.muted && track.readyState === "live" && (element?.readyState ?? 0) >= 2);
    if (element != null) {
      element.srcObject = stream;
      element.addEventListener("playing", check);
      element.addEventListener("emptied", check);
    }
    track?.addEventListener("mute", check);
    track?.addEventListener("unmute", check);
    track?.addEventListener("ended", check);
    check();
    return () => {
      element?.removeEventListener("playing", check);
      element?.removeEventListener("emptied", check);
      track?.removeEventListener("mute", check);
      track?.removeEventListener("unmute", check);
      track?.removeEventListener("ended", check);
    };
  }, [stream]);

  return (
    <>
      {!playing && children}
      <span className="seat-picture" aria-hidden="true">
        <video ref={video} className="seat-picture-frame seat-video" data-playing={playing || undefined} autoPlay muted playsInline />
      </span>
    </>
  );
}
