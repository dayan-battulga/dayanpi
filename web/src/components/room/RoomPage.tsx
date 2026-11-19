import { useState } from "react";
import { useFrame } from "@/components/frame/Frame";
import { PeekDialog } from "@/components/room/PeekDialog";
import { AloneSeat, EmptySeat, SeatCard } from "@/components/room/SeatCard";
import { findCameraMode } from "@/components/track/cameraTracker";
import { useNudge } from "@/hooks/useNudge";
import { useSeatHiding } from "@/hooks/useSeatHiding";
import { ROOM_SIZE } from "@/lib/account";
import { formatDuration } from "@/lib/format";
import { orderSeats, summarizeRoom } from "@/lib/room";

// The room, at / (Room.dc.html with SeatsInfo's seats): today's focus of everyone here who shares it, then a seat per
// account, yours first (minus the offline ones someone hid), and the open seats up to ROOM_SIZE. Everything on it comes from the stream's "room", which the
// Pi builds from what each person shares. Someone else's seat opens the quick peek, and has Nudge when it's time.
export function RoomPage() {
  const { snapshot, user, now, receivedAt, camera } = useFrame();
  const room = snapshot?.room;
  const focus = snapshot?.focus;
  // Your seat's camera: for a desk on this browser's camera unless another computer is already feeding it, and always
  // for one that only takes its picture from here.
  const mode = findCameraMode(focus);
  const showsCamera = mode === "picture" || (mode === "track" && (camera.step !== "off" || focus?.camera_ok !== true || focus.camera_paused === true));
  const everyone = orderSeats(room?.seats ?? [], user?.username);
  const hiding = useSeatHiding(everyone, now);
  // A hidden seat leaves the room but keeps its account's place, so it never turns into an open seat. Never your own:
  // you're here, so the Pi is already bringing it back.
  const seats = everyone.filter((seat) => seat.username === user?.username || hiding.hidden[seat.username] !== true);
  const summary = summarizeRoom(seats);
  const owner = user?.role === "owner";
  const alone = everyone.length === 1;
  const open = Math.max(0, ROOM_SIZE - everyone.length);
  const elapsed = Math.max(0, now - receivedAt);
  const nudger = useNudge();
  const [peeking, setPeeking] = useState<string | null>(null);
  // The peek follows the live seat, and closes if they leave the room.
  const peeked = seats.find((seat) => seat.username === peeking) ?? null;

  return (
    room != null && (
      <div className="room">
        <section className="room-head rise" aria-labelledby="room-total">
          <h1 id="room-total" className="room-total">
            {formatDuration(summary.focusSeconds)}
          </h1>
          <p className="room-caption">
            {summary.caption}
            {/* Only a desk on this browser's camera has a camera to keep on; on a phone it takes its own line. */}
            {focus?.camera_source === "browser" && <span className="room-hint"> · keep your camera on to count your focus</span>}
          </p>
        </section>
        <section className="seats live" aria-label="Seats">
          {seats.map((seat) => (
            <SeatCard
              key={seat.username}
              seat={seat}
              mine={seat.username === user?.username}
              username={user?.username}
              elapsed={elapsed}
              now={now}
              nudger={nudger}
              onPeek={() => setPeeking(seat.username)}
              onHide={() => void hiding.hide(seat)}
              camera={seat.username === user?.username && showsCamera ? camera : undefined}
            />
          ))}
          {alone ? <AloneSeat owner={owner} /> : Array.from({ length: open }, (_, index) => <EmptySeat key={index} owner={owner} />)}
        </section>
        <PeekDialog seat={peeked} username={user?.username} nudger={nudger} now={now} elapsed={elapsed} onClose={() => setPeeking(null)} />
      </div>
    )
  );
}
