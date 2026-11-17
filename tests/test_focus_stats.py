from datetime import datetime

from dayanpi.focus import stats as focus_stats
from dayanpi.focus.tracker import FocusLog, Segment
from dayanpi.focus.stats import HourTotals, add_segment_hours, build_report, list_recent_days


def test_recent_days_counts_back_from_the_last_day():
    assert list_recent_days(datetime(2026, 10, 29), 3) == ["2026-10-27", "2026-10-28", "2026-10-29"]
    assert list_recent_days(datetime(2026, 10, 29), 1) == ["2026-10-29"]


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


def test_main_reads_the_owners_desk_by_default_and_anyones_with_user(tmp_path, monkeypatch, capsys):
    from dayanpi.auth.accounts import AccountStore

    monkeypatch.setenv("DAYANPI_DATA_DIR", str(tmp_path))
    AccountStore(tmp_path / "accounts.db").seed_owner("Dayan", "a password", 0)
    for name in ("dayan", "sam"):
        FocusLog(tmp_path / "users" / name / "focus_log").write({"ts": 0, "day": datetime.now().strftime("%Y-%m-%d"), "event": "state", "state": "working"})
    reports = {}
    for argv in ([], ["--user", "sam"], ["--user", "nobody"]):
        monkeypatch.setattr("sys.argv", ["focus_stats.py", *argv])
        assert focus_stats.main() == 0
        reports[" ".join(argv)] = capsys.readouterr().out
    assert "No focus log lines" not in reports[""] and "No focus log lines" not in reports["--user sam"]
    assert str(tmp_path / "users" / "nobody" / "focus_log") in reports["--user nobody"]


def test_main_without_accounts_asks_whose_desk(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DAYANPI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["focus_stats.py"])
    assert focus_stats.main() == 2
    assert "pass --user" in capsys.readouterr().err
    assert not (tmp_path / "accounts.db").exists(), "it never makes one"
