import json
import math
from datetime import datetime, timedelta

import pytest

from dayanpi.focus import stats as focus_stats
from dayanpi.focus import tracker as focus
from dayanpi.focus.merge import merge_readings
from dayanpi.vision.detector import Box, Detection, FaceReading, FrameReading, Point
from dayanpi.focus.tracker import FocusLog, FocusTracker

BOX = Box(x1=10, y1=10, x2=50, y2=50)
NOON = datetime(2026, 10, 29, 12, 0).timestamp()


def make_reading(person: float = 0.9, phone: float = 0.0, tilt: float | None = None) -> FrameReading:
    faces = [] if tilt is None else [FaceReading(0.9, BOX, [Point(20, 20)] * 5, turn=-0.5, tilt=tilt)]
    reading = FrameReading(
        people=[Detection("person", person, BOX)] if person else [],
        phones=[Detection("phone", phone, BOX)] if phone else [],
        faces=faces,
        elapsed_ms=300.0,
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


def test_seconds_in_state_counts_up_while_working():
    desk = settled_desk()
    desk.work(20)
    status = desk.tracker.status(desk.now)
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
    events = log.read_day("2026-10-29") + log.read_day("2026-10-30")
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
    samples = [event for event in log.read_day("2026-10-29") if event["event"] == "sample"]
    assert len(samples) == 2
    assert samples[0]["tilt"] == 0.5
    assert samples[0]["state"] == "working"


SAMPLE_FIELDS = {"ts", "day", "event", "state", "person", "phone", "turn", "tilt", "ms", "app", "site", "streak_s"}


def read_samples(log: FocusLog) -> list[dict]:
    samples = [event for event in log.read_day("2026-10-29") if event["event"] == "sample"]
    return samples


def test_one_camera_samples_have_exactly_the_same_fields_as_ever(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    Desk(log=log).tick(make_reading(), 31)
    assert set(read_samples(log)[0]) == SAMPLE_FIELDS


def test_samples_add_the_side_cameras_own_numbers_and_keep_the_rest(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    front = make_reading(person=0.8, tilt=0.5)
    side = make_reading(person=0.612, phone=0.456, tilt=0.9)
    Desk(log=log).tick(merge_readings(front, side), 31)
    sample = read_samples(log)[0]
    assert set(sample) == SAMPLE_FIELDS | {"side_person", "side_phone"}
    assert (sample["side_person"], sample["side_phone"]) == (0.61, 0.46)
    assert (sample["person"], sample["phone"]) == (0.8, 0.46), "the existing fields are the best of both cameras"
    assert sample["tilt"] == 0.5, "faces only come from the front camera"
    assert sample["ms"] == 600, "both scans added up"


def test_a_check_with_no_side_frame_leaves_the_side_numbers_out(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    desk = Desk(log=log)
    desk.tick(merge_readings(make_reading(), make_reading()), 31)
    desk.tick(merge_readings(make_reading(), None), 31)
    samples = read_samples(log)
    assert "side_phone" in samples[0]
    assert set(samples[1]) == SAMPLE_FIELDS


def test_side_numbers_in_the_log_do_not_change_the_days_totals(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    Desk(log=log).tick(merge_readings(make_reading(), make_reading(phone=0.6)), 90)
    events = log.read_day("2026-10-29")
    plain = [{key: value for key, value in event.items() if not key.startswith("side_")} for event in events]
    with_side = focus.total_day(focus.replay_day(events, "2026-10-29"))
    without_side = focus.total_day(focus.replay_day(plain, "2026-10-29"))
    assert with_side == without_side
    assert with_side.phone_seconds > 0


def make_old_log_line(seconds: float, event: str, **fields) -> dict:
    line = {"ts": NOON + seconds, "day": "2026-10-29", "event": event, **fields}
    return line


OLD_SAMPLE = {"person": 0.9, "phone": 0.0, "food": 0.61, "drink": 0.4, "turn": None, "tilt": None, "ms": 380, "block": False, "app": None}
OLD_LOG = [
    make_old_log_line(0, "state", state="working", prev="unknown", seconds_in_prev=2.0),
    make_old_log_line(5, "block", action="start", source="api"),
    make_old_log_line(30, "sample", state="working", streak_s=30, side_person=0.7, side_phone=0.0, side_food=0.5, **OLD_SAMPLE),
    make_old_log_line(31, "snack", count=1),
    make_old_log_line(31, "callout", name="snack", text="Snack number 1."),
    make_old_log_line(60, "pickup", count=1),
    make_old_log_line(60, "state", state="phone", prev="working", seconds_in_prev=60.0),
    make_old_log_line(90, "state", state="working", prev="phone", seconds_in_prev=30.0),
    make_old_log_line(100, "block", action="stop", source="gesture"),
    make_old_log_line(120, "sample", state="working", streak_s=30, **OLD_SAMPLE),
]


def test_old_logs_with_snacks_food_and_blocks_replay_and_report_without_them(tmp_path):
    log_dir = tmp_path / "focus_log"
    log_dir.mkdir()
    (log_dir / "2026-10-29.jsonl").write_text("".join(json.dumps(line) + "\n" for line in OLD_LOG))
    log = FocusLog(log_dir)
    events = log.read_day("2026-10-29")
    stripped = [
        {key: value for key, value in event.items() if key not in ("food", "drink", "side_food")}
        for event in events
        if event["event"] not in ("snack", "block") and event.get("name") != "snack"
    ]

    totals = focus.total_day(focus.replay_day(events, "2026-10-29"))
    assert totals == focus.total_day(focus.replay_day(stripped, "2026-10-29"))
    assert (totals.working_seconds, totals.phone_seconds, totals.pickups) == (90, 30, 1)

    later = NOON + 300
    fresh = FocusTracker(started_at=later)
    assert fresh.restore(events, later) == len(OLD_LOG)
    assert "snacks" not in fresh.status(later)["today"]
    assert "block" not in fresh.status(later)

    report = focus_stats.build_report(log, ["2026-10-29"])
    assert "pickups   1" in report
    assert "snack" not in report


def test_restore_rebuilds_today_from_the_log(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    desk = Desk(log=log)
    desk.work(60)
    desk.phone(5)
    desk.work(15)
    desk.work(30)

    later = desk.now + 120
    fresh = FocusTracker(log=log, started_at=later)
    used = fresh.restore(log.read_day("2026-10-29"), later)
    assert used > 0
    status = fresh.status(later)
    assert status["state"] == "unknown"
    assert status["today"]["pickups"] == 1
    # The open segment closes at the last logged event (a sample at 90 s), so up to 30 s is lost: 64 + 17.
    assert status["today"]["working_seconds"] == pytest.approx(81, abs=2)
    assert status["today"]["longest_streak_seconds"] >= 60
    assert [segment["state"] for segment in fresh.segments()][-1] == "unknown"
    assert log.read_day("2026-10-29")[-1]["event"] == "restart"


def test_restore_ignores_other_days(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    yesterday = Desk(start=NOON - 86400, log=log)
    yesterday.work(60)
    fresh = FocusTracker(log=log, started_at=NOON)
    assert fresh.restore(log.read_day("2026-10-28"), NOON) == 0
    assert fresh.status(NOON)["today"]["working_seconds"] == 0
    assert log.read_day("2026-10-29") == []


def test_record_app_logs_changes_only(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    tracker = FocusTracker(log=log, started_at=NOON)
    assert tracker.record_app("Code", NOON) is True
    assert tracker.record_app("Code", NOON + 1) is False
    assert tracker.record_app("Slack", NOON + 2) is True
    assert [event["app"] for event in log.read_day("2026-10-29")] == ["Code", "Slack"]
    assert tracker.status(NOON + 3)["app"] == "Slack"


def test_a_new_site_in_the_same_browser_is_a_change(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    tracker = FocusTracker(log=log, started_at=NOON)
    assert tracker.record_app("Google Chrome", NOON, site="youtube.com") is True
    assert tracker.record_app("Google Chrome", NOON + 1, site="youtube.com") is False
    assert tracker.record_app("Google Chrome", NOON + 2, site="github.com") is True
    assert tracker.record_app("Google Chrome", NOON + 3) is True, "a private window: same app, no site"
    lines = [(event["app"], event["site"]) for event in log.read_day("2026-10-29")]
    assert lines == [("Google Chrome", "youtube.com"), ("Google Chrome", "github.com"), ("Google Chrome", None)]
    assert tracker.status(NOON + 4)["site"] is None


def test_the_site_goes_on_the_samples_next_to_the_app(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    desk = Desk(log=log)
    desk.tracker.record_app("Google Chrome", desk.now, site="youtube.com")
    desk.tick(make_reading(), 31)
    sample = read_samples(log)[0]
    assert (sample["app"], sample["site"]) == ("Google Chrome", "youtube.com")
    assert desk.tracker.status(desk.now)["site"] == "youtube.com"


def test_status_has_the_fields_the_dashboard_needs():
    desk = settled_desk()
    desk.tick(make_reading(tilt=0.4), 1)
    status = desk.tracker.status(desk.now)
    assert set(status) >= {"state", "since", "seconds_in_state", "today", "camera_ok", "last_check", "app"}
    assert "block" not in status
    assert status["last_check"]["tilt"] == 0.4
    assert status["camera_ok"] is True


@pytest.mark.parametrize(
    "seconds, text",
    [(45, "45 seconds"), (60, "1 minute"), (754, "12 minutes"), (3600, "1 hour"), (3905, "1 hour 5 minutes"), (7320, "2 hours 2 minutes")],
)
def test_spoken_durations(seconds, text):
    assert focus.format_spoken_duration(seconds) == text


@pytest.mark.parametrize(
    "seconds, text",
    [
        (0, "0s"),
        (0.9, "0s"),
        (45, "45s"),
        (59.99, "59s"),
        (60, "1m"),
        (12 * 60 + 59, "12m"),
        (3599, "59m"),
        (3600, "1h00"),
        (3900, "1h05"),
        (10 * 3600 + 30 * 60, "10h30"),
        (99 * 3600, "99h00"),
        (-5, "0s"),
        (math.nan, "0s"),
        (math.inf, "999h59"),
        (10**400, "999h59"),
    ],
)
def test_short_durations(seconds, text):
    assert focus.format_duration(seconds) == text


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
    assert log.read_day("2026-10-29")[0]["ts"] == round(NOON + 2.34567, 3)


def test_restart_after_midnight_keeps_the_new_day(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    desk = Desk(start=datetime(2026, 10, 29, 23, 50).timestamp(), log=log)
    desk.work(40 * 60)
    restarted = FocusTracker(log=log, started_at=desk.now + 5)
    restarted.restore(log.read_day("2026-10-30"), desk.now + 5)
    working = restarted.status(desk.now + 5)["today"]["working_seconds"]
    # Midnight to about 00:30, minus the sample gap at the end.
    assert 29 * 60 <= working <= 31 * 60


def test_an_outage_never_counts_as_focus_time(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    desk = Desk(start=datetime(2026, 10, 29, 18, 0).timestamp(), log=log)
    desk.work(5 * 60)
    # The Pi dies at 18:05 and comes back at 21:05.
    back = desk.now + 3 * 3600
    second = FocusTracker(log=log, started_at=back)
    second.restore(log.read_day("2026-10-29"), back)
    for second_tick in range(1, 61):
        second.update(make_reading(), back + second_tick)
    # A third start replays the restart line and must not bridge 18:05 to 21:06.
    third = FocusTracker(log=log, started_at=back + 120)
    third.restore(log.read_day("2026-10-29"), back + 120)
    working = third.status(back + 120)["today"]["working_seconds"]
    assert working < 7 * 60


def test_a_torn_log_line_is_skipped_not_fatal(tmp_path, caplog):
    log = FocusLog(tmp_path / "focus_log")
    desk = Desk(log=log)
    desk.work(3)
    desk.phone(3)
    path = log.day_path("2026-10-29")
    lines = path.read_text().splitlines()
    lines.insert(1, '{"ts": 1, "day": "2026-10-29", "event": "sta')
    path.write_text("\n".join(lines) + "\n")
    events = log.read_day("2026-10-29")
    assert [event["event"] for event in events] == ["state", "pickup", "state"]
    assert "skipped 1 unreadable line" in caplog.text


def test_a_clock_jump_adds_at_most_a_few_seconds():
    desk = settled_desk()
    desk.now += 3600  # NTP steps the clock forward an hour between two checks
    desk.work(1)
    assert desk.tracker.status(desk.now)["today"]["working_seconds"] <= 1 + focus.MAX_STEP_S + 1


def test_day_done_fires_once_per_night_even_across_midnight():
    desk = Desk(start=datetime(2026, 10, 29, 23, 30).timestamp())
    desk.work(60)
    desk.leave(10)
    desk.work(40 * 60)  # back at the desk past midnight
    desk.leave(10)
    assert desk.names() == ["day_done"]
    desk.work(22 * 3600)  # the next evening, past 10 pm again
    desk.leave(10)
    assert desk.names() == ["day_done", "day_done"]


def test_paused_mac_tracking_drops_reports_and_clears_the_current_app(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    tracker = FocusTracker(log=log, started_at=NOON)
    tracker.record_app("Google Chrome", NOON, site="youtube.com")
    tracker.set_mac_tracking(False, NOON + 1)
    assert (tracker.status(NOON + 2)["app"], tracker.status(NOON + 2)["site"]) == (None, None), "cleared right away"
    assert tracker.record_app("Code", NOON + 3) is False
    assert tracker.status(NOON + 4)["app"] is None
    tracker.set_mac_tracking(True, NOON + 5)
    assert tracker.record_app("Code", NOON + 6) is True
    lines = [(event["event"], event.get("app"), event.get("enabled")) for event in log.read_day("2026-10-29")]
    assert lines == [
        ("mac_app", "Google Chrome", None),
        ("mac_tracking", None, False),
        ("mac_tracking", None, True),
        ("mac_app", "Code", None),
    ]


def test_a_new_day_that_starts_paused_says_so(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    desk = Desk(log=log)
    desk.tracker.set_mac_tracking(False, desk.now)
    midnight = datetime(2026, 10, 30, 0, 0, 5).timestamp()
    desk.tracker.update(make_reading(), midnight)
    next_day = [event["event"] for event in log.read_day("2026-10-30")]
    assert next_day[:2] == ["day_start", "mac_tracking"]
    assert [event for event in log.read_day("2026-10-30") if event["event"] == "mac_tracking"][0]["enabled"] is False


def test_the_macs_app_fades_once_the_helper_goes_quiet(tmp_path):
    from dayanpi.focus.tracker import MAC_STALE_S

    log = FocusLog(tmp_path / "focus_log")
    tracker = FocusTracker(log=log, started_at=NOON)
    tracker.record_app("Cursor", NOON)
    tracker.record_app("Cursor", NOON + 60)  # the helper's heartbeat: same app, still there
    assert tracker.status(NOON + 60 + MAC_STALE_S)["app"] == "Cursor"
    assert tracker.status(NOON + 60 + MAC_STALE_S + 1)["app"] is None, "the Mac went to sleep"
    assert tracker.record_app("Cursor", NOON + 600) is True, "back again: a fresh line"
    assert [event["app"] for event in log.read_day("2026-10-29")] == ["Cursor", "Cursor"]


def test_samples_stop_carrying_an_app_the_helper_stopped_reporting(tmp_path):
    from dayanpi.focus.tracker import MAC_STALE_S

    log = FocusLog(tmp_path / "focus_log")
    desk = Desk(log=log)
    desk.tracker.record_app("Google Chrome", desk.now, site="youtube.com")
    desk.tick(make_reading(), int(MAC_STALE_S) + 40)
    samples = read_samples(log)
    assert (samples[0]["app"], samples[0]["site"]) == ("Google Chrome", "youtube.com")
    assert (samples[-1]["app"], samples[-1]["site"]) == (None, None)


def test_the_mac_goes_stale_after_two_missed_heartbeats_but_within_three_minutes():
    from dayanpi.focus.tracker import MAC_STALE_S
    from mac_helper import dayanpi_mac_helper as helper

    assert 2 * helper.HEARTBEAT_INTERVAL_S < MAC_STALE_S <= 3 * 60, "one late heartbeat mustn't blank the sign; a sleeping Mac should, soon"
