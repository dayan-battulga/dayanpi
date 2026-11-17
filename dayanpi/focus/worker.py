"""Runs the detector on the live cameras about once a second and feeds the FocusTracker.

It reads frames from the app's camera streams (the one opener of each camera), so it never
fights the video feed for the device. With a side camera, each check scans a frame from each
camera and merges the two readings. Everything the detector finds goes into the tracker; the
app's hooks get each FocusUpdate (callouts for the speaker, to-do time) and each hand sign that fires.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from dayanpi.hardware.camera import CameraStream
from dayanpi.vision import detector
from dayanpi.vision import hands
from dayanpi.vision.detector import DeskScanner, FrameReading, decode_jpeg
from dayanpi.focus.merge import merge_readings
from dayanpi.focus.overlay import FrameSize, build_overlay
from dayanpi.focus.tracker import FocusTracker, FocusUpdate
from dayanpi.vision.gestures import GestureTracker, read_sign
from dayanpi.utils.threads import LoopThread

logger = logging.getLogger(__name__)

CHECK_INTERVAL_S = 1.0
FRAME_WAIT_S = 0.2  # a new frame normally lands within this; none means the camera is stuck
ERROR_LOG_EVERY = 30  # consecutive failures between log lines, so a dead camera doesn't flood the journal
# systemd-timesyncd creates this once the clock is set from the network. The Pi has no battery
# clock, so until then "now" can be the time it last shut down.
CLOCK_SYNCED_PATH = Path("/run/systemd/timesync/synchronized")
CLOCK_WAIT_S = 60.0
CLOCK_POLL_S = 1.0

UpdateHook = Callable[[FocusUpdate, float], None]
GestureHook = Callable[[str, float], None]


def build_scanner() -> DeskScanner | None:
    """Loads the models, or returns None (focus disabled) when the files aren't there."""
    scanner = None
    missing = [path.name for path in (detector.OBJECT_MODEL_PATH, detector.FACE_MODEL_PATH) if not path.exists()]
    if missing:
        logger.warning("focus tracker disabled: missing model files %s", ", ".join(missing))
    else:
        try:
            scanner = DeskScanner()
        except Exception:
            logger.exception("focus tracker disabled: the models failed to load")
    return scanner


def build_hand_scanner() -> hands.HandScanner | None:
    """The hand models for the hand signs and the phone-in-hand check, or None (both off) when a file is missing or won't load."""
    scanner = None
    missing = [path.name for path in (hands.PALM_MODEL_PATH, hands.HAND_MODEL_PATH) if not path.exists()]
    if missing:
        logger.info("no hand models (%s): hand signs are off and phones count anywhere in the picture", ", ".join(missing))
    else:
        try:
            scanner = hands.HandScanner()
            logger.info("hand models found: hand signs are on")
        except Exception:
            logger.exception("hand signs are off: the hand models failed to load")
    return scanner


def wait_for_clock(synced_path: Path = CLOCK_SYNCED_PATH, timeout_s: float = CLOCK_WAIT_S, poll_s: float = CLOCK_POLL_S) -> bool:
    """Waits for the network clock sync, up to timeout_s. Returns whether it happened.

    Logging an hour of "focused" because the clock jumped forward at boot would poison the
    data, so the worker holds off. No sync file at all (not Raspberry Pi OS) means don't wait.
    """
    synced = synced_path.exists()
    deadline = time.monotonic() + timeout_s
    while not synced and synced_path.parent.parent.exists() and time.monotonic() < deadline:
        time.sleep(poll_s)
        synced = synced_path.exists()
    return synced


@dataclass
class CameraFeed:
    """One camera the worker reads, with its own place in the frame sequence and its own error count."""

    name: str
    stream: CameraStream
    last_frame_id: int = -1
    frame_size: FrameSize | None = None
    failures: int = 0


class FocusWorker(LoopThread):
    def __init__(
        self,
        stream: CameraStream,
        scanner,
        tracker: FocusTracker,
        clock: Callable[[], float] = time.time,
        on_update: UpdateHook | None = None,
        interval_s: float = CHECK_INTERVAL_S,
        on_gesture: GestureHook | None = None,
        wait_for_clock_first: bool = False,
        side_stream: CameraStream | None = None,
        hand_scanner=None,
        is_feeding: Callable[[], bool] = lambda: True,
    ) -> None:
        super().__init__(name="focus-worker", interval_s=interval_s)
        self.front = CameraFeed("front", stream)
        self.side = None if side_stream is None else CameraFeed("side", side_stream)
        self._scanner = scanner
        self._hands = hand_scanner
        self._tracker = tracker
        self._clock = clock
        self._on_update = on_update
        self._on_gesture = on_gesture
        self._wait_for_clock_first = wait_for_clock_first
        self._is_feeding = is_feeding
        self.signs = GestureTracker()
        self.hand_failures = 0
        self.checks = 0
        self.last_update: FocusUpdate | None = None
        self.last_gesture: dict | None = None  # {"name", "at"} of the last hand sign that fired
        self.last_overlay: dict | None = None
        self.last_side_overlay: dict | None = None

    def read_frame(self, feed: CameraFeed) -> FrameReading | None:
        """One detector pass on a frame newer than the last one, or None when the camera gave nothing new.

        latest_frame() would hand back the same JPEG forever when the camera freezes, and the
        tracker would log hours of "focused" from one stale picture.
        """
        reading = None
        arrived = feed.stream.frame_after(feed.last_frame_id, timeout=FRAME_WAIT_S)
        if arrived is not None:
            jpeg, feed.last_frame_id = arrived
            image = decode_jpeg(jpeg)
            if image is not None:
                feed.frame_size = FrameSize(width=image.shape[1], height=image.shape[0])
                reading = self._scanner.scan(image)
                if self._hands is not None:
                    reading = self.check_hands(reading, image)
        return reading

    def check_hands(self, reading: FrameReading, image) -> FrameReading:
        """The hand models on this camera's frame: the hands go into the reading, and only phones near a hand still count.

        The signs only use the front camera's hands (merge_readings keeps those). A hand model
        that throws costs this check's signs and leaves the phones as they were, so it can't
        switch phone detection off.
        """
        started = time.perf_counter()
        found = None
        try:
            found = self._hands.scan(image)
            self.hand_failures = 0
        except Exception:
            self.hand_failures += 1
            if self.hand_failures == 1 or self.hand_failures % ERROR_LOG_EVERY == 0:
                logger.exception("hand check failed (%s in a row)", self.hand_failures)
        checked = replace(
            reading,
            hands=found or [],
            phones=reading.phones if found is None else hands.find_phones_in_hand(reading.phones, found),
            elapsed_ms=reading.elapsed_ms + (time.perf_counter() - started) * 1000,
        )
        return checked

    def read_feed(self, feed: CameraFeed) -> FrameReading | None:
        """read_frame, where a failure only costs this camera this check.

        Each camera counts its own failures: with one shared count, a healthy camera would
        reset it every check, and a broken one would log a traceback every second.
        """
        reading = None
        try:
            reading = self.read_frame(feed)
            feed.failures = 0
        except Exception:
            feed.failures += 1
            if feed.failures == 1 or feed.failures % ERROR_LOG_EVERY == 0:
                logger.exception("focus check failed on the %s camera (%s in a row)", feed.name, feed.failures)
        return reading

    def run_once(self, now: float) -> FocusUpdate:
        front_reading = self.read_feed(self.front)
        side_reading = None if self.side is None else self.read_feed(self.side)
        reading = merge_readings(front_reading, side_reading)
        update = self._tracker.update(reading, now)
        self.checks += 1
        self.last_update = update
        # Swapped in whole, so the stream thread never sees a half-built overlay.
        if front_reading is not None:
            self.last_overlay = build_overlay(front_reading, self.front.frame_size, now)
        if side_reading is not None:
            # No sign boxes on the side feed: signs only fire from the front camera.
            self.last_side_overlay = build_overlay(replace(side_reading, hands=[]), self.side.frame_size, now)
        if self._on_update is not None:
            try:
                self._on_update(update, now)
            except Exception:
                logger.exception("focus update hook failed")
        self.track_gestures(reading, now)
        return update

    def track_gestures(self, reading: FrameReading | None, now: float) -> None:
        sign = None if reading is None else read_sign(reading.hands)
        gesture = self.signs.hold(sign, now)
        if gesture is not None:
            self.last_gesture = {"name": gesture, "at": round(now, 3)}
            logger.info("gesture: %s", gesture)
            if self._on_gesture is not None:
                try:
                    self._on_gesture(gesture, now)
                except Exception:
                    logger.exception("gesture hook failed")

    def before_loop(self) -> None:
        if self._wait_for_clock_first:
            if wait_for_clock():
                logger.info("clock is synced, focus checks starting")
            else:
                logger.warning("no clock sync after %.0f s, focus checks starting anyway", CLOCK_WAIT_S)

    def tick(self) -> None:
        # Off while the desk takes a browser's camera instead (Settings → Camera): no scans, so no stale numbers either.
        if self._is_feeding():
            self.run_once(self._clock())
