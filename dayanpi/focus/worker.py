"""Runs the detector on the live cameras about once a second and feeds the FocusTracker.

It reads frames from the app's camera streams (the one opener of each camera), so it never
fights the video feed for the device. With a side camera, each check scans a frame from each
camera and merges the two readings. Everything the detector finds goes into the tracker; the
app's hooks get each FocusUpdate (speaker, sign) and each gesture.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dayanpi.hardware.camera import CameraStream
from dayanpi.vision import detector
from dayanpi.vision import pose
from dayanpi.vision.detector import DeskScanner, FrameReading, decode_jpeg
from dayanpi.focus.merge import merge_readings
from dayanpi.focus.overlay import FrameSize, build_overlay
from dayanpi.focus.tracker import FocusTracker, FocusUpdate
from dayanpi.vision.gestures import GestureTracker
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
    """Loads the models, or returns None (focus disabled) when the files aren't there.

    With the pose model in models/ the full-frame pass is the pose model, which is what
    makes gestures possible; without it, the plain object model runs and gestures are off.
    """
    scanner = None
    missing = [path.name for path in (detector.OBJECT_MODEL_PATH, detector.FACE_MODEL_PATH) if not path.exists()]
    if missing:
        logger.warning("focus tracker disabled: missing model files %s", ", ".join(missing))
    else:
        try:
            if pose.POSE_MODEL_PATH.exists():
                scanner = pose.PoseDeskScanner()
                logger.info("pose model found: gestures are on")
            else:
                scanner = DeskScanner()
                logger.info("no pose model (%s): gestures are off", pose.POSE_MODEL_PATH.name)
        except Exception:
            logger.exception("focus tracker disabled: the models failed to load")
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
    ) -> None:
        super().__init__(name="focus-worker", interval_s=interval_s)
        self.front = CameraFeed("front", stream)
        self.side = None if side_stream is None else CameraFeed("side", side_stream)
        self._scanner = scanner
        self._tracker = tracker
        self._clock = clock
        self._on_update = on_update
        self._on_gesture = on_gesture
        self._wait_for_clock_first = wait_for_clock_first
        self.gestures = GestureTracker()
        self.checks = 0
        self.last_update: FocusUpdate | None = None
        self.last_gesture: str | None = None
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
        return reading

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
            self.last_side_overlay = build_overlay(side_reading, self.side.frame_size, now)
        if self._on_update is not None:
            try:
                self._on_update(update, now)
            except Exception:
                logger.exception("focus update hook failed")
        self.track_gestures(reading, now)
        return update

    def track_gestures(self, reading: FrameReading | None, now: float) -> None:
        main_pose = None if reading is None else max(reading.poses, key=lambda found: found.confidence, default=None)
        gesture = self.gestures.update(main_pose, now)
        if gesture is not None:
            self.last_gesture = gesture
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
        self.run_once(self._clock())
