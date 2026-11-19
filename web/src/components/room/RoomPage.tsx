import { useState } from "react";
import { useFrame } from "@/components/frame/Frame";
import { PeekDialog } from "@/components/room/PeekDialog";
import { AloneSeat, EmptySeat, SeatCard } from "@/components/room/SeatCard";
import { useNudge } from "@/hooks/useNudge";
import { useSharing } from "@/hooks/useSharing";
import { ROOM_SIZE } from "@/lib/account";
import { formatDuration } from "@/lib/format";
import { orderSeats, summarizeRoom } from "@/lib/room";

// The room, at / (Room.dc.html with SeatsInfo's seats): today's focus of everyone here who shares it, then a seat per
// account, yours first, and the open seats up to ROOM_SIZE. Everything on it comes from the stream's "room", which the
// Pi builds from what each person shares. Someone else's seat opens the quick peek, and has Nudge when it's time.
export function RoomPage() {
  const { snapshot, user, now, receivedAt, camera } = useFrame();
  const room = snapshot?.room;
  const focus = snapshot?.focus;
  // Your seat's camera, for a desk on this browser's camera, unless another computer is already feeding it.
  const showsCamera = focus?.camera_source === "browser" && (camera.step !== "off" || !focus.camera_ok || focus.camera_paused === true);
  const seats = orderSeats(room?.seats ?? [], user?.username);
  const summary = summarizeRoom(seats);
  const owner = user?.role === "owner";
  const alone = seats.length === 1;
  const open = Math.max(0, ROOM_SIZE - seats.length);
  const elapsed = Math.max(0, now - receivedAt);
  const nudger = useNudge();
  // Your seat's Show/Hide my video is Settings → Sharing → Video, held the same way.
  const { sharing, flipSwitch } = useSharing(snapshot?.focus, room, user?.username, now, receivedAt);
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
          <p className="room-caption">{summary.caption}</p>
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
              video={seat.username === user?.username ? { shown: sharing.video, flip: () => void flipSwitch("video", !sharing.video) } : undefined}
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
