import { useEffect, useRef, useState } from "react";

const FRAMES_KEPT = 2; // the one fading in, over the one it replaces

interface Frame {
  at: number;
  url: string;
}

// Someone's once-a-second picture, from /api/people/<username>/picture. Each new frame (a new `at` on the stream) fades
// in over the last one, so it reads as a calm live photo. Mount it only while the seat says there's a picture: it
// fetches nothing else, and unmounting lets go of every frame.
export function SeatPicture({ username, at }: { username: string; at: number }) {
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
        <img key={frame.at} className="seat-picture-frame" src={frame.url} alt="" />
      ))}
    </span>
  );
}
