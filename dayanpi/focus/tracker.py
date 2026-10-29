"""Turns the detector's per-check readings into steady states and today's numbers.

States: "working" (at the desk, no phone), "phone" (phone in hand), "away" (nobody
there) and "unknown" (just started, or no camera frames). The rules and their numbers
come from Dayan's real desk frames; see docs/focus-tracker.md for the reasoning.

Everything time-based takes `now` from the caller, so tests can drive it with fake
clocks. Local-time rules (late night, day done, day rollover) use the Pi's time zone.
"""

import json
import logging
import os
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from dayanpi.paths import DEFAULT_DATA_DIR
from dayanpi.vision.detector import FrameReading, find_best_confidence

logger = logging.getLogger(__name__)

PERSON_MIN = 0.5
PHONE_MIN = 0.25
FOOD_MIN = 0.3

PHONE_WINDOW = 5  # checks
PHONE_ENTER_HITS = 3  # hits in the window to count as "on phone"
PHONE_EXIT_HITS = 0  # hits in the window to count as done with it
AWAY_AFTER_S = 10.0
RETURN_CHECKS = 2  # person seen this many checks in a row to count as back
NO_FRAME_UNKNOWN_S = 30.0

SNACK_WINDOW = 5
SNACK_ENTER_HITS = 3
SNACK_END_S = 120.0  # food unseen this long ends the snack

INSTANT_PICKUP_S = 60.0
LATE_NIGHT_START_HOUR = 1
LATE_NIGHT_END_HOUR = 5
DAY_DONE_START_HOUR = 22
DAY_DONE_END_HOUR = 5
BREAK_OVER_S = 15 * 60
SAMPLE_LOG_INTERVAL_S = 30.0
MAX_STEP_S = 5.0  # checks run every second; a bigger gap is a stall or a clock jump, not time at the desk
MAX_SEGMENTS = 2000

DAY_FORMAT = "%Y-%m-%d"
DATA_DIR_ENV = "DAYANPI_DATA_DIR"


def find_focus_log_dir() -> Path:
    """focus_log/ inside DAYANPI_DATA_DIR, or inside data/ at the repo root."""
    log_dir = Path(os.environ.get(DATA_DIR_ENV, "").strip() or DEFAULT_DATA_DIR) / "focus_log"
    return log_dir


@dataclass
class Segment:
    state: str
    start: float
    end: float | None = None


@dataclass
class DayTotals:
    day: str
    working_seconds: float = 0.0
    phone_seconds: float = 0.0
    away_seconds: float = 0.0
    pickups: int = 0
    snacks: int = 0
    longest_streak_seconds: float = 0.0
    first_seen: float | None = None


@dataclass
class Callout:
    """Something worth telling Dayan. speak=False means log/sign only (nobody's in the room)."""

    name: str
    text: str
    speak: bool = True


@dataclass
class CheckSummary:
    """The numbers from one check, kept for the status API and the sample log."""

    at: float
    person: float = 0.0
    phone: float = 0.0
    food: float = 0.0
    drink: float = 0.0
    turn: float | None = None
    tilt: float | None = None
    elapsed_ms: float = 0.0


@dataclass
class FocusUpdate:
    state: str
    callouts: list[Callout] = field(default_factory=list)


@dataclass
class DayReplay:
    """One day's log, replayed: closed segments plus the counters."""

    day: str
    segments: list[Segment] = field(default_factory=list)
    pickups: int = 0
    snacks: int = 0
    snack_times: list[float] = field(default_factory=list)
    block_active: bool = False
    day_done: bool = False
    last_ts: float | None = None
    events: int = 0


def close_open_segment(segments: list[Segment], end: float | None) -> None:
    if segments and segments[-1].end is None:
        segments[-1].end = end if end is not None else segments[-1].start


def replay_day(events: list[dict], day: str) -> DayReplay:
    """Rebuilds a day from its log lines.

    A "state" or "day_start" line opens a segment. A "restart" line means the service
    was down: the open segment closes at the last line before it (a sample at most 30 s
    old), not at the next state change, so an outage never counts as focus time. The
    last open segment closes at the last line of any kind.
    """
    replay = DayReplay(day=day)
    todays = sorted((event for event in events if event.get("day") == day and "ts" in event), key=lambda event: event["ts"])
    for event in todays:
        kind = event.get("event")
        if kind in ("state", "day_start"):
            close_open_segment(replay.segments, event["ts"])
            replay.segments.append(Segment(state=event.get("state", "unknown"), start=event["ts"]))
        elif kind == "restart":
            close_open_segment(replay.segments, replay.last_ts)
            replay.segments.append(Segment(state="unknown", start=event["ts"]))
        elif kind == "pickup":
            replay.pickups += 1
        elif kind == "snack":
            replay.snacks += 1
            replay.snack_times.append(event["ts"])
        elif kind == "block":
            replay.block_active = event.get("action") == "start"
        elif kind == "callout" and event.get("name") == "day_done":
            replay.day_done = True
        replay.last_ts = event["ts"]
        replay.events += 1
    close_open_segment(replay.segments, replay.last_ts)
    return replay


def total_day(replay: DayReplay) -> DayTotals:
    totals = DayTotals(day=replay.day, pickups=replay.pickups, snacks=replay.snacks)
    for segment in replay.segments:
        length = max(0.0, (segment.end if segment.end is not None else segment.start) - segment.start)
        if segment.state == "working":
            totals.working_seconds += length
            totals.longest_streak_seconds = max(totals.longest_streak_seconds, length)
        elif segment.state == "phone":
            totals.phone_seconds += length
        elif segment.state == "away":
            totals.away_seconds += length
        if segment.state in ("working", "phone") and totals.first_seen is None:
            totals.first_seen = segment.start
    return totals


def format_day(now: float) -> str:
    key = datetime.fromtimestamp(now).strftime(DAY_FORMAT)
    return key


def read_local_hour(now: float) -> int:
    hour = datetime.fromtimestamp(now).hour
    return hour


def is_in_night_window(now: float, start_hour: int, end_hour: int) -> bool:
    """True between start_hour and end_hour, where the window crosses midnight when start > end."""
    hour = read_local_hour(now)
    if start_hour <= end_hour:
        inside = start_hour <= hour < end_hour
    else:
        inside = hour >= start_hour or hour < end_hour
    return inside


def summarize_reading(reading: FrameReading, now: float) -> CheckSummary:
    summary = CheckSummary(
        at=now,
        person=find_best_confidence(reading.people),
        phone=find_best_confidence(reading.phones),
        food=find_best_confidence(reading.food),
        drink=find_best_confidence(reading.drinks),
        elapsed_ms=reading.elapsed_ms,
    )
    if reading.faces:
        face = max(reading.faces, key=lambda found: found.confidence)
        summary.turn = face.turn
        summary.tilt = face.tilt
    return summary


def format_spoken_duration(seconds: float) -> str:
    """Natural phrasing for the voice: "45 seconds", "12 minutes", "1 hour 5 minutes"."""
    whole = int(round(seconds))
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    if whole < 60:
        text = f"{whole} seconds"
    elif hours == 0:
        text = f"{minutes} minute{'s' if minutes != 1 else ''}"
    elif minutes == 0:
        text = f"{hours} hour{'s' if hours != 1 else ''}"
    else:
        text = f"{hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
    return text


class FocusLog:
    """Append-only JSONL log of state changes and events, one file per day. Never frames.

    A sample row every 30 s adds up to well under a megabyte a day, and one file per
    day means a restart only has to read today's file.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock = threading.Lock()

    @property
    def directory(self) -> Path:
        return self._directory

    def day_path(self, day: str) -> Path:
        path = self._directory / f"{day}.jsonl"
        return path

    def write(self, event: dict) -> None:
        line = json.dumps(event, separators=(",", ":"))
        day = event.get("day") or format_day(event.get("ts", 0.0))
        with self._lock:
            try:
                self._directory.mkdir(parents=True, exist_ok=True)
                with self.day_path(day).open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                logger.exception("focus log write failed")

    def read_day(self, day: str) -> list[dict]:
        events = self._read_file(self.day_path(day))
        return events

    def _read_file(self, path: Path) -> list[dict]:
        events = []
        skipped = 0
        with self._lock:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        stripped = line.strip()
                        if stripped:
                            try:
                                events.append(json.loads(stripped))
                            except ValueError:
                                # A power cut mid-write leaves a torn line; the rest of the day is still good.
                                skipped += 1
            except FileNotFoundError:
                pass
            except OSError:
                logger.exception("focus log read failed: %s", path)
        if skipped:
            logger.warning("skipped %s unreadable line(s) in %s", skipped, path)
        return events


class FocusTracker:
    """The state machine. One instance, driven once per detector check."""

    def __init__(self, log: FocusLog | None = None, started_at: float = 0.0) -> None:
        self._lock = threading.Lock()
        self._log = log
        self._started_at = started_at
        self._state = "unknown"
        self._state_since = started_at
        self._last_update_at = started_at
        self._last_frame_at: float | None = None
        self._last_person_at: float | None = None
        self._consecutive_person = 0
        self._phone_hits: deque[bool] = deque(maxlen=PHONE_WINDOW)
        self._food_hits: deque[bool] = deque(maxlen=SNACK_WINDOW)
        self._snacking = False
        self._snack_times: list[float] = []
        self._last_food_at: float | None = None
        self._returned_at: float | None = None
        self._away_since: float | None = None
        self._break_over_fired = False
        self._late_night_fired = False
        self._day_done_fired = False
        self._streak_start: float | None = None
        self._block_active = False
        self._current_app: str | None = None
        self._last_sample_at = started_at
        self._last_check: CheckSummary | None = None
        self._totals = DayTotals(day=format_day(started_at))
        self._segments: list[Segment] = [Segment(state="unknown", start=started_at)]

    # ----- public API -----

    def update(self, reading: FrameReading | None, now: float) -> FocusUpdate:
        with self._lock:
            update = self._update_locked(reading, now)
        return update

    def record_app(self, app: str, now: float) -> bool:
        with self._lock:
            changed = app != self._current_app
            if changed:
                self._current_app = app
                self._write({"event": "mac_app", "app": app}, now)
        return changed

    def record_gesture(self, name: str, now: float) -> None:
        with self._lock:
            self._write({"event": "gesture", "name": name}, now)

    def set_block(self, active: bool, now: float, source: str = "api") -> bool:
        with self._lock:
            changed = self._set_block_locked(active, now, source)
        return changed

    def toggle_block(self, now: float, source: str = "api") -> bool:
        """Flips the block under the lock, so a gesture and the button at the same moment can't cancel out. Returns the new state."""
        with self._lock:
            active = not self._block_active
            self._set_block_locked(active, now, source)
        return active

    def _set_block_locked(self, active: bool, now: float, source: str) -> bool:
        changed = active != self._block_active
        if changed:
            self._block_active = active
            self._break_over_fired = False
            self._write({"event": "block", "action": "start" if active else "stop", "source": source}, now)
        return changed

    def status(self, now: float) -> dict:
        with self._lock:
            status = self._status_locked(now)
        return status

    def segments(self) -> list[dict]:
        with self._lock:
            copied = [asdict(segment) for segment in self._segments]
        return copied

    def snack_times(self) -> list[float]:
        with self._lock:
            copied = list(self._snack_times)
        return copied

    def restore(self, events: list[dict], now: float) -> int:
        """Rebuilds today's totals from the log after a restart. Returns the events used."""
        with self._lock:
            used = self._restore_locked(events, now)
        return used

    # ----- the state machine -----

    def _update_locked(self, reading: FrameReading | None, now: float) -> FocusUpdate:
        self._roll_day_if_needed(now)
        self._accumulate(now)
        callouts: list[Callout] = []
        previous = self._state

        if reading is None:
            next_state = self._state_without_frame(now)
        else:
            self._last_frame_at = now
            check = summarize_reading(reading, now)
            self._last_check = check
            self._note_person(check, now)
            self._phone_hits.append(check.phone >= PHONE_MIN)
            self._food_hits.append(check.food >= FOOD_MIN)
            callouts.extend(self._track_snacks(check, now))
            next_state = self._decide_state(now)
            self._maybe_log_sample(check, now)

        changed = next_state != previous
        if changed:
            callouts.extend(self._transition(previous, next_state, now))
        callouts.extend(self._track_break(now))
        if not is_in_night_window(now, DAY_DONE_START_HOUR, DAY_DONE_END_HOUR):
            # The window runs 22:00-05:00 across midnight, so re-arm by daylight, not at the day rollover.
            self._day_done_fired = False
        update = FocusUpdate(state=self._state, callouts=callouts)
        return update

    def _state_without_frame(self, now: float) -> str:
        next_state = self._state
        frame_age = None if self._last_frame_at is None else now - self._last_frame_at
        if frame_age is None or frame_age >= NO_FRAME_UNKNOWN_S:
            next_state = "unknown"
        return next_state

    def _note_person(self, check: CheckSummary, now: float) -> None:
        if check.person >= PERSON_MIN:
            self._last_person_at = now
            self._consecutive_person += 1
            if self._totals.first_seen is None:
                self._totals.first_seen = now
        else:
            self._consecutive_person = 0

    def _decide_state(self, now: float) -> str:
        present = self._consecutive_person >= RETURN_CHECKS
        # Nobody seen yet counts from startup, so a restart with an empty desk settles on "away" too.
        last_seen = self._last_person_at if self._last_person_at is not None else self._started_at
        gone_for = now - last_seen
        phone_hits = sum(self._phone_hits)

        if self._state in ("away", "unknown"):
            next_state = self._state
            if present:
                next_state = "phone" if phone_hits >= PHONE_ENTER_HITS else "working"
            elif gone_for >= AWAY_AFTER_S:
                next_state = "away"
        elif gone_for >= AWAY_AFTER_S:
            next_state = "away"
        elif self._state == "working":
            next_state = "phone" if phone_hits >= PHONE_ENTER_HITS else "working"
        else:
            next_state = "working" if phone_hits <= PHONE_EXIT_HITS else "phone"
        return next_state

    def _transition(self, previous: str, next_state: str, now: float) -> list[Callout]:
        callouts: list[Callout] = []
        seconds_in_previous = now - self._state_since

        if previous == "working" and self._streak_start is not None:
            self._totals.longest_streak_seconds = max(self._totals.longest_streak_seconds, now - self._streak_start)
        self._streak_start = now if next_state == "working" else None

        if previous == "away" and next_state in ("working", "phone"):
            self._returned_at = now
            callouts.extend(self._callouts_on_return(now))
            self._away_since = None
            self._break_over_fired = False
        if next_state == "away":
            self._away_since = now
            callouts.extend(self._callouts_on_leaving(now))
        if next_state == "phone":
            self._totals.pickups += 1
            self._write({"event": "pickup", "count": self._totals.pickups}, now)
            callouts.extend(self._callouts_on_pickup(now))
        else:
            self._late_night_fired = False

        self._state = next_state
        self._state_since = now
        close_open_segment(self._segments, now)
        self._segments.append(Segment(state=next_state, start=now))
        self._trim_segments()
        self._write({"event": "state", "state": next_state, "prev": previous, "seconds_in_prev": round(seconds_in_previous, 1)}, now)
        for callout in callouts:
            self._write({"event": "callout", "name": callout.name, "text": callout.text}, now)
        return callouts

    def _callouts_on_pickup(self, now: float) -> list[Callout]:
        callouts: list[Callout] = []
        if self._returned_at is not None and now - self._returned_at <= INSTANT_PICKUP_S:
            since_return = format_spoken_duration(now - self._returned_at)
            callouts.append(Callout("instant_pickup", f"Sat down {since_return} ago and already on the phone."))
        if is_in_night_window(now, LATE_NIGHT_START_HOUR, LATE_NIGHT_END_HOUR) and not self._late_night_fired:
            self._late_night_fired = True
            callouts.append(Callout("late_night_phone", f"It's {read_local_hour(now)} in the morning. Put the phone down and go to sleep."))
        return callouts

    def _callouts_on_return(self, now: float) -> list[Callout]:
        callouts: list[Callout] = []
        if self._away_since is not None and now - self._away_since >= BREAK_OVER_S:
            away_for = format_spoken_duration(now - self._away_since)
            callouts.append(Callout("long_break", f"Welcome back. That break ran {away_for}."))
        return callouts

    def _callouts_on_leaving(self, now: float) -> list[Callout]:
        callouts: list[Callout] = []
        if is_in_night_window(now, DAY_DONE_START_HOUR, DAY_DONE_END_HOUR) and not self._day_done_fired:
            self._day_done_fired = True
            callouts.append(Callout("day_done", self._day_done_text()))
        return callouts

    def _day_done_text(self) -> str:
        totals = self._totals
        text = (
            f"Day done. {format_spoken_duration(totals.working_seconds)} focused, "
            f"{totals.pickups} pickup{'s' if totals.pickups != 1 else ''}, "
            f"longest streak {format_spoken_duration(totals.longest_streak_seconds)}."
        )
        return text

    def _track_break(self, now: float) -> list[Callout]:
        """Flags a break that's run long during a work block (logged + sign; the phone ping hooks in here later)."""
        callouts: list[Callout] = []
        if self._block_active and self._state == "away" and self._away_since is not None and not self._break_over_fired:
            if now - self._away_since >= BREAK_OVER_S:
                self._break_over_fired = True
                callouts.append(Callout("break_over", "Break's over. Back to it.", speak=False))
                self._write({"event": "callout", "name": "break_over", "text": callouts[-1].text}, now)
        return callouts

    def _track_snacks(self, check: CheckSummary, now: float) -> list[Callout]:
        callouts: list[Callout] = []
        if check.food >= FOOD_MIN:
            self._last_food_at = now
        food_hits = sum(self._food_hits)
        if not self._snacking and food_hits >= SNACK_ENTER_HITS:
            self._snacking = True
            self._totals.snacks += 1
            self._snack_times.append(now)
            self._write({"event": "snack", "count": self._totals.snacks}, now)
            callouts.append(Callout("snack", f"Snack number {self._totals.snacks}.", speak=False))
        elif self._snacking and self._last_food_at is not None and now - self._last_food_at >= SNACK_END_S:
            self._snacking = False
            self._food_hits.clear()
        return callouts

    # ----- totals, segments, day rollover -----

    def _accumulate(self, now: float) -> None:
        elapsed = min(max(0.0, now - self._last_update_at), MAX_STEP_S)
        self._last_update_at = now
        if self._state == "working":
            self._totals.working_seconds += elapsed
            if self._streak_start is not None:
                self._totals.longest_streak_seconds = max(self._totals.longest_streak_seconds, now - self._streak_start)
        elif self._state == "phone":
            self._totals.phone_seconds += elapsed
        elif self._state == "away":
            self._totals.away_seconds += elapsed

    def _roll_day_if_needed(self, now: float) -> None:
        today = format_day(now)
        if today != self._totals.day:
            self._accumulate(now)
            self._write({"event": "day_summary", **self._totals_dict()}, now, day=self._totals.day)
            self._totals = DayTotals(day=today)
            self._snack_times = []
            close_open_segment(self._segments, now)
            self._segments = [Segment(state=self._state, start=now)]
            if self._state == "working":
                self._streak_start = now
            self._write({"event": "day_start", "state": self._state}, now)

    def _trim_segments(self) -> None:
        if len(self._segments) > MAX_SEGMENTS:
            del self._segments[: len(self._segments) - MAX_SEGMENTS]

    def _maybe_log_sample(self, check: CheckSummary, now: float) -> None:
        if now - self._last_sample_at >= SAMPLE_LOG_INTERVAL_S:
            self._last_sample_at = now
            sample = {
                "event": "sample",
                "state": self._state,
                "person": round(check.person, 2),
                "phone": round(check.phone, 2),
                "food": round(check.food, 2),
                "drink": round(check.drink, 2),
                "turn": None if check.turn is None else round(check.turn, 2),
                "tilt": None if check.tilt is None else round(check.tilt, 2),
                "ms": round(check.elapsed_ms),
                "block": self._block_active,
                "app": self._current_app,
                "streak_s": None if self._streak_start is None else round(now - self._streak_start),
            }
            self._write(sample, now)

    def _write(self, event: dict, now: float, day: str | None = None) -> None:
        if self._log is not None:
            stamped = {"ts": round(now, 3), "day": day or format_day(now), **event}
            self._log.write(stamped)

    # ----- status -----

    def _totals_dict(self) -> dict:
        totals = asdict(self._totals)
        for key in ("working_seconds", "phone_seconds", "away_seconds", "longest_streak_seconds"):
            totals[key] = round(totals[key], 1)
        return totals

    def _status_locked(self, now: float) -> dict:
        frame_age = None if self._last_frame_at is None else round(now - self._last_frame_at, 1)
        status = {
            "state": self._state,
            "since": round(self._state_since, 3),
            "seconds_in_state": round(max(0.0, now - self._state_since), 1),
            "today": self._totals_dict(),
            "block": {"active": self._block_active},
            "app": self._current_app,
            "camera_ok": frame_age is not None and frame_age < NO_FRAME_UNKNOWN_S,
            "last_check": None if self._last_check is None else asdict(self._last_check),
        }
        return status

    # ----- restore after a restart -----

    def _restore_locked(self, events: list[dict], now: float) -> int:
        replay = replay_day(events, format_day(now))
        self._totals = total_day(replay)
        self._snack_times = list(replay.snack_times)
        self._segments = replay.segments + [Segment(state="unknown", start=now)]
        self._trim_segments()
        self._state = "unknown"
        self._state_since = now
        self._last_update_at = now
        self._block_active = replay.block_active
        self._day_done_fired = replay.day_done
        if replay.events:
            self._write({"event": "restart", "restored_events": replay.events}, now)
        return replay.events
