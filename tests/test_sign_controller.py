import time
from datetime import datetime

import numpy as np

from dayanpi.sign import renderer as sign
from dayanpi.sign import controller as sign_controller
from dayanpi.focus.tracker import Callout, FocusTracker
from dayanpi.sign.controller import SignController

NOON = datetime(2026, 10, 29, 12, 0).timestamp()
LATE = datetime(2026, 10, 29, 23, 30).timestamp()


class FakeOutput:
    def __init__(self) -> None:
        self.frames = []

    def show(self, frame: np.ndarray) -> None:
        self.frames.append(frame.copy())


def make_controller(now: float = NOON) -> SignController:
    tracker = FocusTracker(started_at=now)
    controller = SignController(tracker, [FakeOutput()], clock=lambda: now)
    return controller


def test_renders_the_now_page_by_default():
    controller = make_controller()
    frame = controller.render(NOON + 1)
    assert frame.shape == (sign.SIGN_HEIGHT, sign.SIGN_WIDTH, 3)
    assert frame.dtype == np.uint8
    assert controller.page == "now"


def test_pages_flip_and_fall_back_to_now():
    controller = make_controller()
    assert controller.flip_page(1) == "today"
    assert controller.flip_page(1) == "summary"
    assert controller.flip_page(1) == "now"
    assert controller.flip_page(-1) == "summary"
    controller.flip_page(-1)
    assert controller.page == "today"
    controller.render(NOON + sign_controller.PAGE_FLIP_RETURN_S + 1)
    assert controller.page == "now"


def test_a_hand_flip_to_the_summary_page_falls_back_too():
    controller = make_controller()
    controller.flip_page(1)
    controller.flip_page(1)
    assert controller.page == "summary"
    controller.render(NOON + sign_controller.PAGE_FLIP_RETURN_S + 1)
    assert controller.page == "now"


def test_callouts_scroll_then_clear():
    controller = make_controller()
    controller.show_callout(Callout("instant_pickup", "Sat down 30 seconds ago and already on the phone."))
    first = controller.render(NOON + 0.5)
    later = controller.render(NOON + 1.5)
    assert not np.array_equal(first, later), "the text should have scrolled"
    assert controller._active is not None
    width = sign.measure_callout("Sat down 30 seconds ago and already on the phone.")
    controller.render(NOON + width / sign_controller.SCROLL_PX_PER_S + 1)
    assert controller._active is None


def test_day_done_switches_to_the_summary_page_for_a_while():
    controller = make_controller()
    controller.show_callout(Callout("day_done", "Day done. 2 hours focused, 3 pickups, longest streak 40 minutes."))
    assert controller.page == "summary"
    controller.render(NOON + 60)
    assert controller.page == "summary"
    controller.render(NOON + sign_controller.SUMMARY_SHOW_S + 1)
    assert controller.page == "now"


def test_work_block_dims_the_sign_but_not_a_callout():
    controller = make_controller()
    controller._tracker.set_block(True, NOON)
    assert controller._brightness(NOON + 1) == sign_controller.AMBIENT_BRIGHTNESS
    controller.show_callout(Callout("snack", "Snack number 1.", speak=False))
    controller.render(NOON + 1)
    assert controller._brightness(NOON + 1) == sign_controller.DAY_BRIGHTNESS


def test_night_brightness():
    controller = make_controller(LATE)
    assert controller._brightness(LATE) == sign_controller.NIGHT_BRIGHTNESS


def test_loop_pushes_frames_to_every_output():
    controller = make_controller()
    output = controller._outputs[0]
    controller.start()
    deadline = time.monotonic() + 2.0
    while controller.frames < 3 and time.monotonic() < deadline:
        time.sleep(0.02)
    controller.stop()
    assert len(output.frames) >= 3
    assert output.frames[0].shape == (sign.SIGN_HEIGHT, sign.SIGN_WIDTH, 3)


def test_queue_is_bounded():
    controller = make_controller()
    for index in range(10):
        controller.show_callout(Callout("snack", f"Snack number {index}.", speak=False))
    assert len(controller._queue) == sign_controller.CALLOUT_QUEUE_MAX
