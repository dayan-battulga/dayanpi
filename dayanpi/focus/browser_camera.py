"""A browser's camera feeding a desk (the /track page): each check's numbers. The seat's small picture can ride along with
a reading (step 7), but it never reaches the tracker: app.py keeps it on the desk, through the sharing switches.

The page sends what the tracker reads from a check, and this turns it into the reading the Pi's own cameras would
make, so the desk's tracker, log, to-do time and day pages work the same way. The desk's hand sign hold is its own,
like the worker's.
"""

import threading
from dataclasses import dataclass

from dayanpi.focus.tracker import FocusTracker, FocusUpdate
from dayanpi.vision.detector import Box, Detection, FrameReading
from dayanpi.vision.gestures import GestureTracker

# The page checks once a second, or slower. One that arrives late lets the next one through early, so: one a
# second in the long run, two close together at most.
READINGS_PER_S = 1.0
READING_BURST = 2.0
# Nothing for this long, and each tick counts as a check without a frame, like a stuck camera (30 s of them is unknown).
QUIET_S = 1.5
# The page keeps the boxes; the tracker only reads confidences.
NO_BOX = Box(0.0, 0.0, 0.0, 0.0)


@dataclass
class BrowserCheck:
    person: float
    phone: float  # only phones near a hand, like the Pi's
    sign: str | None  # the hand sign this check saw, before any hold
    elapsed_ms: float


@dataclass
class BrowserUpdate:
    update: FocusUpdate
    gesture: str | None  # a hand sign that fired on this check


def build_reading(check: BrowserCheck) -> FrameReading:
    people = [Detection("person", check.person, NO_BOX)] if check.person > 0 else []
    phones = [Detection("phone", check.phone, NO_BOX)] if check.phone > 0 else []
    reading = FrameReading(people=people, phones=phones, faces=[], elapsed_ms=check.elapsed_ms)
    return reading


class BrowserCamera:
    """One desk's browser camera: the rate limit, the pause, the hand sign hold and when it last heard anything."""

    def __init__(self, tracker: FocusTracker) -> None:
        self._tracker = tracker
        self._lock = threading.Lock()
        self._tokens = READING_BURST
        self._tokens_at: float | None = None
        self.signs = GestureTracker()
        self.last_reading_at: float | None = None
        self.paused = False
        self.last_gesture: dict | None = None  # {"name", "at"} of the last hand sign that fired

    def take(self, check: BrowserCheck, now: float) -> BrowserUpdate | None:
        """None when it came too soon after the ones before, which the route refuses. A reading ends a pause."""
        with self._lock:
            taken = None
            if self._spend_token(now):
                self.paused = False
                self.last_reading_at = now
                update = self._tracker.update(build_reading(check), now)
                gesture = self.signs.hold(check.sign, now)
                if gesture is not None:
                    self.last_gesture = {"name": gesture, "at": round(now, 3)}
                taken = BrowserUpdate(update, gesture)
        return taken

    def tick(self, now: float) -> FocusUpdate | None:
        """Once a second. After QUIET_S without a reading it's a check without a frame; otherwise None."""
        with self._lock:
            update = None
            if self.last_reading_at is None or now - self.last_reading_at >= QUIET_S:
                update = self._tracker.update(None, now)
                self.signs.hold(None, now)
        return update

    def pause(self, now: float) -> FocusUpdate:
        """The page turned its camera off on purpose: unknown right away, and paused until the next reading."""
        with self._lock:
            self.paused = True
            update = self._tracker.stop_seeing(now)
        return update

    def _spend_token(self, now: float) -> bool:
        waited = 0.0 if self._tokens_at is None else max(0.0, now - self._tokens_at)
        self._tokens = min(READING_BURST, self._tokens + waited * READINGS_PER_S)
        self._tokens_at = now
        allowed = self._tokens >= 1.0
        if allowed:
            self._tokens -= 1.0
        return allowed
