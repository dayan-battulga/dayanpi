import { AnimatePresence, m } from "motion/react";
import { useRef, useState } from "react";
import { Switch } from "@/components/ui/switch";
import { showToast } from "@/components/ui/toaster";
import { formatClock } from "@/lib/format";
import { request } from "@/lib/http";
import { SPRINGS } from "@/lib/motion";
import { listSharedPieces, readInitial } from "@/lib/room";
import type { FocusStatus, Room, Seat, Sharing } from "@/lib/types";

// A snapshot built just before a switch flipped can still arrive after the reply, so the reply wins for a moment.
const SWITCH_HOLD_S = 2.5;

// History isn't in the mockup; it sits after the to-dos like the rest. Status is always on, so it's a plain row.
const SWITCHES: { key: keyof Sharing; label: string }[] = [
  { key: "focus", label: "Focus time" },
  { key: "todos", label: "To-do list" },
  { key: "history", label: "History" },
  { key: "apps", label: "Apps" },
  { key: "sites", label: "Sites" },
  { key: "video", label: "Video" },
];

const DEFAULT_SHARING: Sharing = { focus: true, todos: true, history: true, apps: false, sites: false, video: false };

const PIECE_IN = { opacity: 1, transition: SPRINGS.enter };
const PIECE_OUT = { opacity: 0, transition: SPRINGS.exit };

interface SharingSectionProps {
  focus: FocusStatus | undefined;
  room: Room | null | undefined;
  username: string;
  now: number;
  receivedAt: number;
}

interface Held {
  sharing: Sharing;
  seat: Seat | null; // the reply's, once it's in
  at: number;
  until: number;
}

// Settings → Share with the room (Settings.dc.html): your switches, and your seat exactly as everyone else gets it,
// from the Pi: the stream's room, or the reply to the switch you just flipped, whose pieces fade in or out.
export function SharingSection({ focus, room, username, now, receivedAt }: SharingSectionProps) {
  const [held, setHeld] = useState<Held | null>(null);
  const latest = useRef(0);
  const holding = held != null && now < held.until;
  const sharing = holding ? held.sharing : (focus?.sharing ?? DEFAULT_SHARING);
  const streamed = room?.seats.find((entry) => entry.username === username) ?? null;
  const seat = holding && held.seat != null ? held.seat : streamed;
  const seatAt = holding && held.seat != null ? held.at : receivedAt;

  const flipSwitch = async (key: keyof Sharing, on: boolean) => {
    const asked = ++latest.current;
    setHeld({ sharing: { ...sharing, [key]: on }, seat: null, at: now, until: Infinity });
    const reply = await request<{ sharing: Sharing; seat: Seat }>("POST", "/api/sharing", { [key]: on });
    const answer = reply.body;
    // Only the newest flip's answer counts, so two quick ones can't land out of order.
    if (asked === latest.current) {
      const at = Date.now() / 1000;
      setHeld(answer != null ? { sharing: answer.sharing, seat: answer.seat, at, until: at + SWITCH_HOLD_S } : null);
    }
    if (answer == null) {
      showToast("Couldn't change what the room sees");
    }
  };

  return (
    <section aria-labelledby="settings-sharing">
      <h2 id="settings-sharing" className="settings-title">
        Share with the room
      </h2>
      <p className="settings-lead">Your own desk always shows you everything.</p>
      <div className="share-body">
        <ul className="share-switches">
          <li className="setting-row">
            Status
            <span className="setting-meta">Always on</span>
          </li>
          {SWITCHES.map((entry) => (
            <li key={entry.key} className="setting-row">
              {entry.label}
              <Switch label={entry.label} checked={sharing[entry.key]} onCheckedChange={(on) => void flipSwitch(entry.key, on)} />
            </li>
          ))}
        </ul>
        <div className="share-preview">
          <p className="share-preview-label">What the room sees</p>
          {seat != null && (
            <>
              <div className="share-tile" data-state={seat.state} aria-label={`Your seat: ${seat.name}`}>
                <span className="share-initial" aria-hidden="true">
                  {readInitial(seat.name)}
                </span>
                <div className="share-tile-foot">
                  <span className="share-name">{seat.name}</span>
                  <span className="share-timer">{seat.seconds_in_state == null ? "offline" : formatClock(seat.seconds_in_state + Math.max(0, now - seatAt))}</span>
                </div>
              </div>
              <ul className="share-pieces" aria-label="What else the room sees">
                <AnimatePresence initial={false}>
                  {listSharedPieces(seat).map((piece) => (
                    <m.li key={piece.key} className="share-piece" initial={{ opacity: 0 }} animate={PIECE_IN} exit={PIECE_OUT}>
                      {piece.text}
                    </m.li>
                  ))}
                </AnimatePresence>
              </ul>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
