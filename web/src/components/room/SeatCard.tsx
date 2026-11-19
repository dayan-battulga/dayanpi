import { Plus, Video, VideoOff } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link } from "react-router";
import { NudgeButton } from "@/components/room/NudgeButton";
import { SeatPicture } from "@/components/room/SeatPicture";
import { CameraControl } from "@/components/track/CameraControl";
import type { Camera } from "@/hooks/useCamera";
import type { Nudger } from "@/hooks/useNudge";
import { formatClock, formatDuration } from "@/lib/format";
import { SEAT_WORDS, describeSeatLine, findDoneShare, readInitial } from "@/lib/room";
import type { Seat } from "@/lib/types";

// Two ripple rings, the second 0.6 s behind, two rounds of 1.8 s each: SPEC's ripple, then they stop.
const RIPPLE_S = 4.2;

interface SeatCardProps {
  seat: Seat;
  mine: boolean;
  username: string | undefined;
  elapsed: number; // seconds since the snapshot the seat came in
  now: number;
  nudger: Nudger;
  onPeek: () => void; // someone else's seat opens the quick peek
  video?: { shown: boolean; flip: () => void }; // your own seat's Show/Hide my video (Settings → Sharing → Video)
  camera?: Camera; // your own seat, while your desk is on this browser's camera
}

// Your own camera, live on your seat while it's on: straight from the camera, so nothing extra goes to the Pi. It sits
// where the picture would, so it gets the picture's shade and white text.
function LiveVideo({ stream }: { stream: MediaStream }) {
  const video = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    if (video.current !== null) {
      video.current.srcObject = stream;
    }
  }, [stream]);
  return (
    <span className="seat-picture" aria-hidden="true">
      <video ref={video} className="seat-picture-frame seat-live" autoPlay muted playsInline />
    </span>
  );
}

// One person's seat (SeatsInfo.dc.html): the lamp in their state color, their once-a-second picture (or their initial
// when there's none), today's total, their name and timer, the current to-do and app, and the to-dos-done bar. Each
// detail only if they share it.
export function SeatCard({ seat, mine, username, elapsed, now, nudger, onPeek, video, camera }: SeatCardProps) {
  const line = describeSeatLine(seat);
  const done = findDoneShare(seat);
  const seconds = seat.seconds_in_state == null ? null : seat.seconds_in_state + elapsed;
  // Everyone in the room sees the rings leave a seat that was just nudged. They're gone long before the next nudge can
  // come (10 minutes), so each one mounts them fresh and they play once.
  const nudgedAgo = seat.nudge?.age_s == null ? null : seat.nudge.age_s + elapsed;
  const live = camera?.step === "on" ? camera.preview : null;
  return (
    <article className="seat" data-state={seat.state} aria-label={`${seat.name}, ${mine ? "you" : SEAT_WORDS[seat.state]}`}>
      {!mine && <button type="button" className="seat-peek" aria-label={`Peek at ${seat.name}`} aria-haspopup="dialog" onClick={onPeek} />}
      <span className="seat-initial" aria-hidden="true">
        {readInitial(seat.name)}
      </span>
      {live != null ? <LiveVideo stream={live} /> : seat.picture != null && <SeatPicture username={seat.username} at={seat.picture.at} />}
      {nudgedAgo != null && nudgedAgo < RIPPLE_S && (
        <span className="seat-ripples" aria-hidden="true">
          <span />
          <span />
        </span>
      )}
      <NudgeButton seat={seat} username={username} nudger={nudger} elapsed={elapsed} now={now} kind="bell" />
      {(camera != null || video != null) && (
        <div className="seat-tools">
          {camera != null && <CameraControl camera={camera} place="seat" />}
          {video != null && (
            <button type="button" className="video-toggle" aria-pressed={video.shown} aria-label={video.shown ? "Hide my video" : "Show my video"} onClick={video.flip}>
              {video.shown ? <Video size={18} strokeWidth={1.8} aria-hidden="true" /> : <VideoOff size={18} strokeWidth={1.8} aria-hidden="true" />}
            </button>
          )}
        </div>
      )}
      {seat.focus_seconds != null && (
        <span className="seat-chip">
          {formatDuration(seat.focus_seconds)}
          <span className="seat-chip-today"> today</span>
        </span>
      )}
      <div className="seat-foot">
        <div className="seat-row">
          <span className="seat-name">{mine ? "You" : seat.name}</span>
          <span className="seat-timer">{seconds == null ? "offline" : formatClock(seconds)}</span>
        </div>
        {(line.todo != null || line.app != null) && (
          <p className="seat-line">
            {line.todo}
            {line.paused && <span className="seat-paused"> · paused</span>}
            {line.app != null && <span className="seat-app">{`${line.todo != null ? " · " : ""}${line.app}`}</span>}
          </p>
        )}
      </div>
      {done != null && seat.todos != null && (
        <div className="seat-bar">
          <span className="sr-only">{`${seat.todos.done} of ${seat.todos.total} to-dos done`}</span>
          <span className="seat-bar-fill" style={{ width: `${done}%` }} aria-hidden="true" />
        </div>
      )}
    </article>
  );
}

// A seat nobody has yet. Only the owner can invite, so only the owner's says so.
export function EmptySeat({ owner }: { owner: boolean }) {
  return (
    <article className="seat seat-empty" aria-label="Open seat">
      {owner && (
        <Link className="seat-invite" to="/settings" state={{ section: "room" }}>
          <Plus strokeWidth={1.8} aria-hidden="true" />
          Invite
        </Link>
      )}
    </article>
  );
}

// Room's "just you" moment: nobody else has an account yet.
export function AloneSeat({ owner }: { owner: boolean }) {
  return (
    <article className="seat seat-empty seat-alone" aria-label="Nobody else here">
      <p className="seat-alone-title">Just you for now</p>
      {owner && (
        <Link className="button button-line" to="/settings" state={{ section: "room" }}>
          Invite someone
        </Link>
      )}
    </article>
  );
}
