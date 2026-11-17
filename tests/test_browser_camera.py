from dataclasses import asdict

from dayanpi.focus.browser_camera import BrowserCamera, BrowserCheck, build_reading
from dayanpi.focus.camera_source import CameraSourceSetting
from dayanpi.focus.tracker import NO_FRAME_UNKNOWN_S, FocusLog, FocusTracker
from dayanpi.vision.detector import Box, Detection, FrameReading
from dayanpi.vision.gestures import HOLD_SECONDS, PEACE

START = 1_800_000_000.0


def make_pi_reading(person: float, phone: float) -> FrameReading:
    """What the Pi's own camera hands the tracker, boxes and all."""
    people = [Detection("person", person, Box(120, 40, 420, 470))] if person > 0 else []
    phones = [Detection("phone", phone, Box(300, 300, 360, 400))] if phone > 0 else []
    reading = FrameReading(people=people, phones=phones, faces=[], elapsed_ms=180.0)
    return reading


def run_checks(tracker: FocusTracker, readings: list[FrameReading]) -> list[str]:
    states = [tracker.update(reading, START + second).state for second, reading in enumerate(readings)]
    return states


def test_a_browser_reading_moves_the_tracker_like_the_same_pi_reading(tmp_path):
    numbers = [(0.9, 0.0)] * 4 + [(0.9, 0.7)] * 4 + [(0.0, 0.0)] * 12 + [(0.85, 0.0)] * 3
    pi = FocusTracker(FocusLog(tmp_path / "pi"), started_at=START)
    browser = FocusTracker(FocusLog(tmp_path / "browser"), started_at=START)
    pi_states = run_checks(pi, [make_pi_reading(person, phone) for person, phone in numbers])
    browser_states = run_checks(browser, [build_reading(BrowserCheck(person, phone, None, 180.0)) for person, phone in numbers])
    end = START + len(numbers)
    assert browser_states == pi_states
    assert "phone" in pi_states and "away" in pi_states and pi_states[-1] == "working"
    assert browser.status(end) == pi.status(end)
    assert browser.segments() == pi.segments()
    day = pi.status(end)["today"]
    assert asdict(pi._totals) == asdict(browser._totals) and day["pickups"] == 1


def test_a_quiet_browser_means_unknown_after_30_s_like_a_stuck_camera(tmp_path):
    tracker = FocusTracker(FocusLog(tmp_path), started_at=START)
    camera = BrowserCamera(tracker)
    for second in range(3):
        camera.take(BrowserCheck(0.9, 0.0, None, 150.0), START + second)
    before = tracker.status(START + 3)["state"]
    ticks = [camera.tick(START + 2 + second) for second in range(2, int(NO_FRAME_UNKNOWN_S) + 2)]
    states = [update.state for update in ticks]
    assert before == "working"
    assert states == ["working"] * 28 + ["unknown"] * 2, "unknown once the last frame is 30 s old"


def test_a_tick_right_after_a_reading_does_nothing(tmp_path):
    camera = BrowserCamera(FocusTracker(FocusLog(tmp_path), started_at=START))
    camera.take(BrowserCheck(0.9, 0.0, None, 150.0), START)
    assert camera.tick(START + 0.5) is None
    assert camera.tick(START + 1.5) is not None


def test_readings_come_about_once_a_second_with_room_for_one_late_one(tmp_path):
    camera = BrowserCamera(FocusTracker(FocusLog(tmp_path), started_at=START))
    check = BrowserCheck(0.9, 0.0, None, 150.0)
    steady = [camera.take(check, START + second) is not None for second in range(5)]
    flood = [camera.take(check, START + 4 + tenth / 10) is not None for tenth in range(1, 101)]
    steady_again = BrowserCamera(FocusTracker(FocusLog(tmp_path / "again"), started_at=START))
    late_then_on_time = [steady_again.take(check, START + at) is not None for at in (0, 1, 2, 3.4, 4, 5)]
    assert steady == [True] * 5
    assert sum(flood) == 11, "ten readings a second for 10 s: one a second, plus the one the burst saved"
    assert late_then_on_time == [True] * 6, "a late one, then the next one on time"


def test_a_peace_sign_fires_once_from_the_browsers_readings_after_its_hold(tmp_path):
    camera = BrowserCamera(FocusTracker(FocusLog(tmp_path), started_at=START))
    fired = [camera.take(BrowserCheck(0.9, 0.0, PEACE, 150.0), START + second).gesture for second in range(4)]
    assert fired == [None, PEACE, None, None]
    assert HOLD_SECONDS[PEACE] == 1.0
    assert camera.last_gesture == {"name": PEACE, "at": START + 1}


def test_a_hold_ends_when_the_browser_goes_quiet(tmp_path):
    camera = BrowserCamera(FocusTracker(FocusLog(tmp_path), started_at=START))
    camera.take(BrowserCheck(0.9, 0.0, PEACE, 150.0), START)
    camera.tick(START + 2)
    camera.tick(START + 3)
    assert camera.take(BrowserCheck(0.9, 0.0, PEACE, 150.0), START + 4).gesture is None, "a new hold starts here"


def test_pause_is_unknown_right_away_and_ends_with_the_next_reading(tmp_path):
    tracker = FocusTracker(FocusLog(tmp_path), started_at=START)
    camera = BrowserCamera(tracker)
    for second in range(3):
        camera.take(BrowserCheck(0.9, 0.0, None, 150.0), START + second)
    paused = camera.pause(START + 3)
    was_paused = camera.paused
    first_back = camera.take(BrowserCheck(0.9, 0.0, None, 150.0), START + 60)
    second_back = camera.take(BrowserCheck(0.9, 0.0, None, 150.0), START + 61)
    assert (paused.state, was_paused, camera.paused) == ("unknown", True, False)
    assert (first_back.update.state, second_back.update.state) == ("unknown", "working"), "seen twice in a row again"


def test_the_camera_source_is_saved_and_a_bad_file_means_no_pick(tmp_path):
    path = tmp_path / "camera_source.json"
    setting = CameraSourceSetting(path)
    assert setting.source is None
    assert setting.set("browser") and not setting.set("browser")
    assert CameraSourceSetting(path).source == "browser"
    path.write_text('{"source": "webcam"}')
    assert CameraSourceSetting(path).source is None
    path.write_text("not json")
    assert CameraSourceSetting(path).source is None
