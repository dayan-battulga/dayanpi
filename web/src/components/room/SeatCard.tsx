import { Mic, Plus, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link } from "react-router";
import { NudgeButton } from "@/components/room/NudgeButton";
import { SeatPicture, SeatVideo } from "@/components/room/SeatPicture";
import { SoundBars } from "@/components/room/TalkControl";
import { GoalRing, formatGoalProgress } from "@/components/shared/GoalRing";
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
  onHide: () => void; // someone else's offline seat's ×
  camera?: Camera; // your own seat, while your desk is on this browser's camera
  goal?: { seconds: number; minutes: number }; // your own seat, with your daily goal: only you ever see it
  talk?: SeatTalk;
  video?: MediaStream; // someone else's smooth video, while it's connected
}

// Who hears whom, on a seat (RoomV2.dc.html): the chip with sound bars while they talk, or while you do on your own seat
// ("To everyone", "To Sam only", "To you"), a ring, and on someone else's seat the mic to talk to just them.
export interface SeatTalk {
  chip?: string;
  ring?: "on" | "soft"; // on: talking, or talking to you; soft: the one person you're talking to
  mic?: { on: boolean; onToggle: () => void }; // only while they take direct talk and talking works here
}

function TalkChip({ text }: { text: string }) {
  return (
    <span className="talk-chip">
      <SoundBars />
      <span className="talk-chip-text">{text}</span>
    </span>
  );
}

// Your own camera, live on your seat while it's on: straight from the camera, so nothing extra goes to the Pi. It sits
// where the picture would, so it gets the picture's shade and white text, and it's a mirror, like the picture there.
function LiveVideo({ stream }: { stream: MediaStream }) {
  const video = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    if (video.current !== null) {
      video.current.srcObject = stream;
    }
  }, [stream]);
  return (
    <span className="seat-picture" aria-hidden="true">
      <video ref={video} className="seat-picture-frame seat-live is-mirrored" autoPlay muted playsInline />
    </span>
  );
}

// One person's seat (SeatsInfo.dc.html): the lamp in their state color, their once-a-second picture (or their initial
// when there's none), today's total, their name and timer, the current to-do and app, and the to-dos-done bar. Each
// detail only if they share it.
export function SeatCard({ seat, mine, username, elapsed, now, nudger, onPeek, onHide, camera, goal, talk, video }: SeatCardProps) {
  const line = describeSeatLine(seat);
  const done = findDoneShare(seat);
  const seconds = seat.seconds_in_state == null ? null : seat.seconds_in_state + elapsed;
  // Everyone in the room sees the rings leave a seat that was just nudged. They're gone long before the next nudge can
  // come (10 minutes), so each one mounts them fresh and they play once.
  const nudgedAgo = seat.nudge?.age_s == null ? null : seat.nudge.age_s + elapsed;
  const live = camera?.step === "on" ? camera.preview : null;
  return (
    <article className="seat" data-state={seat.state} data-lamp={seat.lamp} data-talk={talk?.ring} aria-label={`${seat.name}, ${mine ? "you" : SEAT_WORDS[seat.state]}`}>
      {!mine && <button type="button" className="seat-peek" aria-label={`Peek at ${seat.name}`} aria-haspopup="dialog" onClick={onPeek} />}
      <span className="seat-initial" aria-hidden="true">
        {readInitial(seat.name)}
      </span>
      {/* The Pi's say-so (seat.picture: video shared, here, at the desk) gates the smooth video too: hidden is hidden. */}
      {live != null ? (
        <LiveVideo stream={live} />
      ) : (
        seat.picture != null &&
        (video != null && !mine ? (
          <SeatVideo stream={video}>
            <SeatPicture username={seat.username} at={seat.picture.at} />
          </SeatVideo>
        ) : (
          <SeatPicture username={seat.username} at={seat.picture.at} mirrored={mine} />
        ))
      )}
      {nudgedAgo != null && nudgedAgo < RIPPLE_S && (
        <span className="seat-ripples" aria-hidden="true">
          <span />
          <span />
        </span>
      )}
      {mine ? (
        (camera != null || talk?.chip != null) && (
          <div className="seat-tools">
            {talk?.chip != null && <TalkChip text={talk.chip} />}
            {camera != null && <CameraControl camera={camera} place="seat" />}
          </div>
        )
      ) : (
        <div className="seat-corner">
          {/* First, so while it's hidden it never pushes the chip in from the corner. */}
          {talk?.mic != null && (
            <button type="button" className="seat-mic" data-on={talk.mic.on || undefined} aria-pressed={talk.mic.on} onClick={talk.mic.onToggle}>
              <Mic size={14} strokeWidth={2} aria-hidden="true" />
              {talk.mic.on ? `Talking to ${seat.name}` : `Talk to ${seat.name}`}
            </button>
          )}
          {talk?.chip != null && <TalkChip text={talk.chip} />}
          <NudgeButton seat={seat} username={username} nudger={nudger} elapsed={elapsed} now={now} kind="bell" />
        </div>
      )}
      {!mine && !seat.here && (
        <button type="button" className="seat-hide" aria-label={`Hide ${seat.name}’s seat`} onClick={onHide}>
          <X size={16} strokeWidth={1.8} aria-hidden="true" />
        </button>
      )}
      {goal != null ? (
        <span className="seat-chip seat-chip-goal">
          <GoalRing seconds={goal.seconds} goalMinutes={goal.minutes} size="small" />
          {formatGoalProgress(goal.seconds, goal.minutes)}
        </span>
      ) : (
        seat.focus_seconds != null && (
          <span className="seat-chip">
            {formatDuration(seat.focus_seconds)}
            <span className="seat-chip-today"> today</span>
          </span>
        )
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
