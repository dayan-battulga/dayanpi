"""Decides what the LED sign shows and pushes frames to its outputs.

Pages: NOW (state + timer), TODAY (totals), SUMMARY (end of day). Callouts scroll
across on top of whatever page is up, then it goes back. During a work block the
sign dims to "ambient" so it isn't a distraction, and it dims at night too.

Outputs get a (32, 128, 3) frame a few times a second: the PreviewOutput for the
website always, the PanelOutput once the panels exist.
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from dayanpi.sign import renderer
from dayanpi.focus.tracker import Callout, FocusTracker, is_in_night_window
from dayanpi.sign.renderer import CalloutPage, NowPage, SummaryPage, TodayPage
from dayanpi.utils.threads import LoopThread

logger = logging.getLogger(__name__)

SIGN_FPS = 8
SCROLL_PX_PER_S = 24
CALLOUT_QUEUE_MAX = 4
SUMMARY_SHOW_S = 15 * 60
PAGE_FLIP_RETURN_S = 20.0  # a flipped-to page falls back to NOW after this
AMBIENT_BRIGHTNESS = 0.35
NIGHT_BRIGHTNESS = 0.4
DAY_BRIGHTNESS = 0.8
NIGHT_START_HOUR = 23
NIGHT_END_HOUR = 7

PAGES = ("now", "today", "summary")
CALLOUT_ICONS = {
    "instant_pickup": "phone",
    "late_night_phone": "moon",
    "long_break": "check",
    "break_over": "alert",
    "day_done": "check",
    "snack": "food",
    "gesture": "hand",
}
CALLOUT_COLORS = {
    "instant_pickup": (200, 40, 40),
    "late_night_phone": (120, 90, 200),
    "long_break": (60, 160, 90),
    "break_over": (200, 120, 0),
    "day_done": (60, 160, 90),
    "snack": (200, 140, 40),
    "gesture": (80, 140, 200),
}
DEFAULT_CALLOUT_COLOR = (200, 200, 200)


@dataclass
class ActiveCallout:
    callout: Callout
    started_at: float


class SignController(LoopThread):
    def __init__(self, tracker: FocusTracker, outputs: list, clock=time.time, fps: int = SIGN_FPS) -> None:
        super().__init__(name="sign", interval_s=1.0 / fps)
        self._tracker = tracker
        self._outputs = outputs
        self._clock = clock
        self._lock = threading.Lock()
        self._page = "now"
        self._page_flipped_at: float | None = None
        self._summary_until: float | None = None
        self._queue: deque[Callout] = deque(maxlen=CALLOUT_QUEUE_MAX)
        self._active: ActiveCallout | None = None
        self.frames = 0

    # ----- control -----

    def show_callout(self, callout: Callout) -> None:
        with self._lock:
            self._queue.append(callout)
            if callout.name == "day_done":
                self._summary_until = self._clock() + SUMMARY_SHOW_S
                self._page = "summary"

    def flip_page(self, step: int) -> str:
        with self._lock:
            index = (PAGES.index(self._page) + step) % len(PAGES)
            self._page = PAGES[index]
            self._page_flipped_at = self._clock()
            page = self._page
        return page

    @property
    def page(self) -> str:
        return self._page

    # ----- rendering -----

    def render(self, now: float) -> np.ndarray:
        with self._lock:
            self._advance(now)
            page = self._build_page(now)
            brightness = self._brightness(now)
        frame = renderer.render_page(page, brightness=brightness)
        return frame

    def _advance(self, now: float) -> None:
        if self._active is not None:
            scrolled = (now - self._active.started_at) * SCROLL_PX_PER_S
            if scrolled > renderer.measure_callout(self._active.callout.text):
                self._active = None
        if self._active is None and self._queue:
            self._active = ActiveCallout(callout=self._queue.popleft(), started_at=now)
        if self._summary_until is not None and now >= self._summary_until:
            self._summary_until = None
            self._page = "now"
        # A flipped-to page falls back to NOW, including the summary when it was flipped to by hand
        # rather than put up by the day-done callout.
        if self._page_flipped_at is not None and now - self._page_flipped_at >= PAGE_FLIP_RETURN_S and self._summary_until is None:
            self._page_flipped_at = None
            self._page = "now"

    def _build_page(self, now: float):
        status = self._tracker.status(now)
        today = status["today"]
        if self._active is not None:
            callout = self._active.callout
            page = CalloutPage(
                text=callout.text,
                icon=CALLOUT_ICONS.get(callout.name, "alert"),
                color=CALLOUT_COLORS.get(callout.name, DEFAULT_CALLOUT_COLOR),
                scroll_px=int((now - self._active.started_at) * SCROLL_PX_PER_S),
            )
        elif self._page == "today":
            page = TodayPage(
                working_seconds=today["working_seconds"],
                phone_seconds=today["phone_seconds"],
                pickups=today["pickups"],
                snacks=today["snacks"],
            )
        elif self._page == "summary":
            page = SummaryPage(
                working_seconds=today["working_seconds"],
                phone_seconds=today["phone_seconds"],
                pickups=today["pickups"],
                longest_streak_seconds=today["longest_streak_seconds"],
            )
        else:
            page = NowPage(
                state=status["state"],
                seconds_in_state=status["seconds_in_state"],
                pickups_today=today["pickups"],
            )
        return page

    def _brightness(self, now: float) -> float:
        night = is_in_night_window(now, NIGHT_START_HOUR, NIGHT_END_HOUR)
        brightness = NIGHT_BRIGHTNESS if night else DAY_BRIGHTNESS
        block_active = self._tracker.status(now)["block"]["active"]
        if block_active and self._active is None:
            brightness = min(brightness, AMBIENT_BRIGHTNESS)
        return brightness

    def tick(self) -> None:
        frame = self.render(self._clock())
        for output in self._outputs:
            output.show(frame)
        self.frames += 1
