import json
from datetime import datetime, timedelta

import pytest

import focus
from detector import Box, Detection, FaceReading, FrameReading, Point
from focus import FocusLog, FocusTracker

BOX = Box(x1=10, y1=10, x2=50, y2=50)
NOON = datetime(2026, 10, 29, 12, 0).timestamp()


def make_reading(person: float = 0.9, phone: float = 0.0, food: float = 0.0, drink: float = 0.0, tilt: float | None = None) -> FrameReading:
    faces = [] if tilt is None else [FaceReading(0.9, BOX, [Point(20, 20)] * 5, turn=-0.5, tilt=tilt)]
    reading = FrameReading(
        people=[Detection("person", person, BOX)] if person else [],
        phones=[Detection("phone", phone, BOX)] if phone else [],
        faces=faces,
        elapsed_ms=300.0,
        food=[Detection("donut", food, BOX)] if food else [],
        drinks=[Detection("cup", drink, BOX)] if drink else [],
    )
    return reading


class Desk:
    """Drives a tracker one check per second with a fake clock."""

    def __init__(self, start: float = NOON, log: FocusLog | None = None) -> None:
        self.now = start
        self.tracker = FocusTracker(log=log, started_at=start)
        self.callouts = []

    def tick(self, reading: FrameReading | None, seconds: int = 1) -> str:
        state = self.tracker.status(self.now)["state"]
        for _ in range(seconds):
            self.now += 1.0
            update = self.tracker.update(reading, self.now)
            self.callouts.extend(update.callouts)
            state = update.state
        return state

    def work(self, seconds: int = 1) -> str:
        return self.tick(make_reading(), seconds)

    def phone(self, seconds: int = 1) -> str:
        return self.tick(make_reading(phone=0.6), seconds)

    def leave(self, seconds: int = 1) -> str:
        return self.tick(make_reading(person=0.0), seconds)

    def names(self) -> list[str]:
        return [callout.name for callout in self.callouts]


def settled_desk() -> Desk:
    desk = Desk()
    desk.work(3)
    return desk


def test_starts_unknown_then_working_after_two_sightings():
    desk = Desk()
    assert desk.tracker.status(desk.now)["state"] == "unknown"
    assert desk.work(1) == "unknown"
    assert desk.work(1) == "working"


def test_empty_desk_settles_on_away():
    desk = Desk()
    assert desk.leave(9) == "unknown"
    assert desk.leave(1) == "away"


def test_phone_needs_three_of_five_and_exits_after_five_misses():
    desk = settled_desk()
    assert desk.phone(2) == "working"
    assert desk.phone(1) == "phone"
    assert desk.tracker.status(desk.now)["today"]["pickups"] == 1
    assert desk.work(4) == "phone"
    assert desk.work(1) == "working"
    assert desk.tracker.status(desk.now)["today"]["pickups"] == 1


def test_one_phone_glimpse_does_not_count():
    desk = settled_desk()
    desk.phone(1)
    assert desk.work(10) == "working"
    assert desk.tracker.status(desk.now)["today"]["pickups"] == 0


def test_away_after_ten_seconds_and_back_after_two_sightings():
    desk = settled_desk()
    assert desk.leave(9) == "working"
    assert desk.leave(1) == "away"
    assert desk.work(1) == "away"
    assert desk.work(1) == "working"
    states = [segment["state"] for segment in desk.tracker.segments()]
    assert states == ["unknown", "working", "away", "working"]


def test_single_missed_person_check_is_ignored():
    desk = settled_desk()
    desk.leave(1)
    assert desk.work(1) == "working"


def test_totals_and_streak_add_up():
    desk = settled_desk()
    desk.work(30)
    desk.phone(3)
    desk.phone(7)
    desk.work(5)
    desk.leave(10)
    today = desk.tracker.status(desk.now)["today"]
    # Working: 1 settling + 30 + the 2 checks before the phone counted + 1 at the switch,
    # then 4 misses + 1 at the switch back + 9 before away + 1 at the switch = 44.
    assert today["working_seconds"] == pytest.approx(44, abs=1.5)
    # Phone: 7 + the 5 checks it took to decide the phone was gone = 12.
    assert today["phone_seconds"] == pytest.approx(12, abs=1.5)
    assert today["away_seconds"] == pytest.approx(0, abs=1.5)
    assert today["pickups"] == 1
    assert today["longest_streak_seconds"] >= 32


def test_live_streak_counts_up_while_working():
    desk = settled_desk()
    desk.work(20)
    status = desk.tracker.status(desk.now)
    assert status["streak_seconds"] == pytest.approx(21, abs=1.5)
    assert status["seconds_in_state"] == pytest.approx(21, abs=1.5)


def test_instant_pickup_callout_only_right_after_returning():
    desk = settled_desk()
    desk.leave(10)
    desk.work(2)
    desk.phone(3)
    assert desk.names() == ["instant_pickup"]
    assert "ago and already on the phone" in desk.callouts[0].text

    late = settled_desk()
    late.leave(10)
    late.work(70)
    late.phone(3)
    assert late.names() == []


def test_late_night_pickup_says_go_to_sleep_once():
    desk = Desk(start=datetime(2026, 10, 29, 1, 30).timestamp())
    desk.work(3)
    desk.phone(3)
    desk.work(5)
    desk.phone(3)
    assert desk.names() == ["late_night_phone", "late_night_phone"]

    daytime = settled_desk()
    daytime.phone(3)
    assert daytime.names() == []


def test_day_done_when_leaving_late_fires_once():
    desk = Desk(start=datetime(2026, 10, 29, 23, 0).timestamp())
    desk.work(60)
    desk.leave(10)
    desk.work(2)
    desk.leave(10)
    assert desk.names() == ["day_done"]
    assert desk.callouts[0].text.startswith("Day done. 1 minute focused")


def test_long_break_is_announced_on_return():
    desk = settled_desk()
    desk.leave(17 * 60)
    assert desk.names() == []
    desk.work(2)
    assert desk.names() == ["long_break"]
    # Away started 10 s after the last sighting, so a bit under 17 minutes.
    assert "16 minutes" in desk.callouts[0].text


def test_break_over_flag_during_a_block_is_silent():
    desk = settled_desk()
    assert desk.tracker.set_block(True, desk.now) is True
    assert desk.tracker.set_block(True, desk.now) is False
    desk.leave(10)
    assert desk.tracker.status(desk.now)["state"] == "away"
    desk.leave(15 * 60 - 1)
    assert desk.names() == []
    desk.leave(1)
    assert desk.names() == ["break_over"]
    assert desk.callouts[0].speak is False
    desk.leave(60)
    assert desk.names() == ["break_over"]


def test_snacks_count_once_per_sitting():
    desk = settled_desk()
    desk.tick(make_reading(food=0.6), 3)
    assert desk.tracker.status(desk.now)["today"]["snacks"] == 1
    assert desk.names() == ["snack"]
    desk.tick(make_reading(food=0.6), 60)
    assert desk.tracker.status(desk.now)["today"]["snacks"] == 1
    desk.work(119)
    desk.tick(make_reading(food=0.6), 3)
    assert desk.tracker.status(desk.now)["today"]["snacks"] == 1
    desk.work(121)
    desk.tick(make_reading(food=0.6), 3)
    assert desk.tracker.status(desk.now)["today"]["snacks"] == 2


def test_no_frames_keeps_state_briefly_then_unknown():
    desk = settled_desk()
    assert desk.tick(None, 29) == "working"
    assert desk.tick(None, 1) == "unknown"
    assert desk.tracker.status(desk.now)["camera_ok"] is False
    assert desk.work(1) == "working"


def test_day_rollover_resets_totals_and_logs_a_summary(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    desk = Desk(start=datetime(2026, 10, 29, 23, 59, 30).timestamp(), log=log)
    desk.work(20)
    desk.work(20)
    events = log.read_all()
    kinds = [event["event"] for event in events]
    assert "day_summary" in kinds
    summary = next(event for event in events if event["event"] == "day_summary")
    assert summary["day"] == "2026-10-29"
    assert summary["working_seconds"] > 20
    assert desk.tracker.status(desk.now)["today"]["day"] == "2026-10-30"
    assert desk.tracker.status(desk.now)["today"]["working_seconds"] < 15


def test_log_lines_carry_ts_and_day(tmp_path):
    log = FocusLog(tmp_path / "nested" / "focus_log")
    desk = Desk(log=log)
    desk.work(3)
    desk.phone(3)
    lines = (tmp_path / "nested" / "focus_log" / "2026-10-29.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    assert first["event"] == "state"
    assert first["state"] == "working"
    assert first["day"] == "2026-10-29"
    assert first["ts"] > NOON
    assert [event["event"] for event in log.read_day("2026-10-29")] == ["state", "pickup", "state"]
    assert log.read_day("2000-01-01") == []


def test_samples_are_logged_every_thirty_seconds(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    desk = Desk(log=log)
    desk.tick(make_reading(tilt=0.5), 61)
    samples = [event for event in log.read_all() if event["event"] == "sample"]
    assert len(samples) == 2
    assert samples[0]["tilt"] == 0.5
    assert samples[0]["state"] == "working"


def test_restore_rebuilds_today_from_the_log(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    desk = Desk(log=log)
    desk.work(60)
    desk.phone(5)
    desk.work(10)
    desk.tick(make_reading(food=0.6), 5)
    desk.tracker.set_block(True, desk.now)
    desk.work(30)

    later = desk.now + 120
    fresh = FocusTracker(log=log, started_at=later)
    used = fresh.restore(log.read_all(), later)
    assert used > 0
    status = fresh.status(later)
    assert status["state"] == "unknown"
    assert status["today"]["pickups"] == 1
    assert status["today"]["snacks"] == 1
    # The open segment closes at the last logged event (a sample at 90 s), so up to 30 s is lost: 64 + 17.
    assert status["today"]["working_seconds"] == pytest.approx(81, abs=2)
    assert status["today"]["longest_streak_seconds"] >= 60
    assert status["block"]["active"] is True
    assert [segment["state"] for segment in fresh.segments()][-1] == "unknown"
    assert log.read_all()[-1]["event"] == "restart"


def test_restore_ignores_other_days(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    yesterday = Desk(start=NOON - 86400, log=log)
    yesterday.work(60)
    fresh = FocusTracker(log=log, started_at=NOON)
    assert fresh.restore(log.read_all(), NOON) == 0
    assert fresh.status(NOON)["today"]["working_seconds"] == 0
    assert log.days() == ["2026-10-28"]
    assert log.read_day("2026-10-29") == []
    assert len(log.read_day("2026-10-28")) == len(log.read_all())


def test_record_app_logs_changes_only(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    tracker = FocusTracker(log=log, started_at=NOON)
    assert tracker.record_app("Code", NOON) is True
    assert tracker.record_app("Code", NOON + 1) is False
    assert tracker.record_app("Slack", NOON + 2) is True
    assert [event["app"] for event in log.read_all()] == ["Code", "Slack"]
    assert tracker.status(NOON + 3)["app"] == "Slack"


def test_status_has_the_fields_the_dashboard_needs():
    desk = settled_desk()
    desk.tick(make_reading(tilt=0.4), 1)
    status = desk.tracker.status(desk.now)
    assert set(status) >= {"state", "since", "seconds_in_state", "streak_seconds", "today", "block", "camera_ok", "last_check", "app", "snacking"}
    assert status["last_check"]["tilt"] == 0.4
    assert status["camera_ok"] is True


@pytest.mark.parametrize(
    "seconds, text",
    [(45, "45 seconds"), (60, "1 minute"), (754, "12 minutes"), (3600, "1 hour"), (3905, "1 hour 5 minutes"), (7320, "2 hours 2 minutes")],
)
def test_spoken_durations(seconds, text):
    assert focus.format_spoken_duration(seconds) == text


def test_night_window_crosses_midnight():
    assert focus.is_in_night_window(datetime(2026, 10, 29, 23, 30).timestamp(), 22, 5)
    assert focus.is_in_night_window(datetime(2026, 10, 29, 2, 0).timestamp(), 22, 5)
    assert not focus.is_in_night_window(datetime(2026, 10, 29, 12, 0).timestamp(), 22, 5)
    assert focus.is_in_night_window(datetime(2026, 10, 29, 3, 0).timestamp(), 1, 5)
    assert not focus.is_in_night_window(datetime(2026, 10, 29, 5, 0).timestamp(), 1, 5)


def test_timestamps_are_rounded_in_log_without_breaking_restore(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    tracker = FocusTracker(log=log, started_at=NOON)
    tracker.update(make_reading(), NOON + 1.23456)
    tracker.update(make_reading(), NOON + 2.34567)
    assert log.read_all()[0]["ts"] == round(NOON + 2.34567, 3)
