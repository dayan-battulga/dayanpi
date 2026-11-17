import { useFrame } from "@/components/frame/Frame";
import { AloneSeat, EmptySeat, SeatCard } from "@/components/room/SeatCard";
import { ROOM_SIZE } from "@/lib/account";
import { formatDuration } from "@/lib/format";
import { orderSeats, summarizeRoom } from "@/lib/room";

// The room, at / (Room.dc.html with SeatsInfo's seats): today's focus of everyone here who shares it, then a seat per
// account, yours first, and the open seats up to ROOM_SIZE. Everything on it comes from the stream's "room", which the
// Pi builds from what each person shares.
export function RoomPage() {
  const { snapshot, user, now, receivedAt } = useFrame();
  const room = snapshot?.room;
  const seats = orderSeats(room?.seats ?? [], user?.username);
  const summary = summarizeRoom(seats);
  const owner = user?.role === "owner";
  const alone = seats.length === 1;
  const open = Math.max(0, ROOM_SIZE - seats.length);
  const elapsed = Math.max(0, now - receivedAt);

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
            <SeatCard key={seat.username} seat={seat} mine={seat.username === user?.username} seconds={seat.seconds_in_state == null ? null : seat.seconds_in_state + elapsed} />
          ))}
          {alone ? <AloneSeat owner={owner} /> : Array.from({ length: open }, (_, index) => <EmptySeat key={index} owner={owner} />)}
        </section>
      </div>
    )
  );
}
