from datetime import datetime

import focus_stats
from focus import FocusLog, Segment
from focus_stats import HourTotals, add_segment_hours, build_report, recent_days


def test_recent_days_counts_back_from_the_last_day():
    assert recent_days(datetime(2026, 10, 29), 3) == ["2026-10-27", "2026-10-28", "2026-10-29"]
    assert recent_days(datetime(2026, 10, 29), 1) == ["2026-10-29"]


def test_segment_hours_split_at_the_hour():
    totals = HourTotals()
    start = datetime(2026, 10, 29, 13, 50).timestamp()
    add_segment_hours(totals, Segment("working", start, start + 20 * 60))
    assert totals.working[13] == 600
    assert totals.working[14] == 600
    add_segment_hours(totals, Segment("phone", start + 20 * 60, start + 21 * 60))
    assert totals.phone[14] == 60
    assert totals.pickups[14] == 1


def test_report_reads_the_log_and_builds_the_hour_table(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    base = datetime(2026, 10, 29, 9, 0).timestamp()
    log.write({"ts": base, "day": "2026-10-29", "event": "state", "state": "working", "prev": "unknown"})
    log.write({"ts": base + 3600, "day": "2026-10-29", "event": "pickup", "count": 1})
    log.write({"ts": base + 3600, "day": "2026-10-29", "event": "state", "state": "phone", "prev": "working"})
    log.write({"ts": base + 3900, "day": "2026-10-29", "event": "state", "state": "working", "prev": "phone"})
    log.write({"ts": base + 7200, "day": "2026-10-29", "event": "sample", "state": "working"})
    yesterday = base - 86400
    log.write({"ts": yesterday, "day": "2026-10-28", "event": "state", "state": "working", "prev": "unknown"})
    log.write({"ts": yesterday + 1800, "day": "2026-10-28", "event": "state", "state": "away", "prev": "working"})

    report = build_report(log, ["2026-10-28", "2026-10-29"])

    assert "2026-10-28  first 09:00  focus    30m" in report
    # 09:00-10:00 working, 10:05-11:00 working (closed at the 11:00 sample) = 1h55.
    assert "2026-10-29  first 09:00  focus   1h55  phone     5m  pickups   1" in report
    assert "focus by hour" in report
    assert "09:00" in report and "10:00" in report


def test_report_says_so_when_there_is_nothing(tmp_path):
    report = build_report(FocusLog(tmp_path / "focus_log"), ["2026-10-29"])
    assert report.startswith("No focus log lines for 2026-10-29..2026-10-29")


def test_main_prints_today(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["focus_stats.py", "--log-dir", str(tmp_path / "focus_log")])
    assert focus_stats.main() == 0
    assert "No focus log lines" in capsys.readouterr().out
