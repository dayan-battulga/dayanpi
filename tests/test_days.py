from datetime import datetime

import pytest

from dayanpi.focus.days import (
    GoalSetting,
    count_app_seconds,
    count_overlap_seconds,
    build_day_page,
    find_finished_todos,
    find_seconds_until_midnight,
    read_month,
    read_page_totals,
    write_missing_pages,
)
from dayanpi.focus.tracker import FocusLog

DAY = "2026-11-14"


def at(hour: int, minute: int = 0, day: int = 14) -> float:
    moment = datetime(2026, 11, day, hour, minute).timestamp()
    return moment


def line(hour: int, minute: int, event: str, **fields) -> dict:
    stamped = {"ts": at(hour, minute), "day": DAY, "event": event, **fields}
    return stamped


SAMPLE_DAY = [
    line(9, 0, "state", state="working"),
    line(9, 5, "block", action="start", source="api"),  # older logs have these; new pages skip them
    line(10, 0, "state", state="phone"),
    line(10, 0, "pickup"),
    line(10, 10, "state", state="working"),
    line(10, 20, "todo", action="done", id="a", text="reply to emails", seconds=480),
    line(10, 25, "todo", action="undone", id="a", text="reply to emails", seconds=480),
    line(10, 40, "todo", action="done", id="b", text="finish the report", seconds=4320),
    line(11, 0, "block", action="stop", source="gesture"),
    line(11, 0, "state", state="away"),
    line(11, 30, "state", state="working"),
    line(11, 45, "todo", action="done", id="a", text="reply to emails", seconds=600),
    line(12, 0, "sample", person=0.9, phone=0.0),
]

SAMPLE_PAGE = """---
date: 2026-11-14
focus_minutes: 140
phone_minutes: 10
away_minutes: 30
pickups: 1
best_streak_minutes: 60
todos_done: 2
youtube_minutes: 0
---

# Saturday, November 14, 2026

## Totals
- Focus: 2h20
- Phone: 10m
- Away: 30m
- Pickups: 1
- Best streak: 1h00
- YouTube: 0s

## To-dos done
- finish the report (1h12)
- reply to emails (10m)

## Apps
- None
"""


def test_a_sample_day_page():
    assert build_day_page(SAMPLE_DAY, DAY) == SAMPLE_PAGE


def test_a_day_with_no_todos_says_none():
    page = build_day_page([line(9, 0, "state", state="working"), line(9, 30, "sample")], DAY)
    assert "## To-dos done\n- None\n" in page
    assert read_page_totals(page)["focus_minutes"] == 30


def test_a_day_with_no_log():
    page = build_day_page([], DAY)
    assert page.endswith("# Saturday, November 14, 2026\n\nNothing was logged on this day.\n")
    assert read_page_totals(page) == {
        "focus_minutes": 0,
        "phone_minutes": 0,
        "away_minutes": 0,
        "pickups": 0,
        "best_streak_minutes": 0,
        "todos_done": 0,
        "youtube_minutes": 0,
    }


def test_only_todos_still_checked_at_the_end_of_the_day_count():
    lines = [
        line(9, 0, "todo", action="done", id="a", text="a", seconds=60),
        line(9, 5, "todo", action="undone", id="a", text="a", seconds=60),
        line(9, 10, "todo", action="added", id="c", text="c", seconds=0),
    ]
    assert find_finished_todos(lines, DAY) == []


def test_lines_from_another_day_are_ignored():
    stray = {**line(9, 0, "todo", action="done", id="x", text="yesterday's", seconds=60), "day": "2026-11-13"}
    assert "yesterday's" not in build_day_page(SAMPLE_DAY + [stray], DAY)


def write_log(log: FocusLog, day: str, hour: int = 9) -> None:
    moment = datetime.strptime(f"{day} {hour:02d}:00", "%Y-%m-%d %H:%M").timestamp()
    log.write({"ts": moment, "day": day, "event": "state", "state": "working"})
    log.write({"ts": moment + 600, "day": day, "event": "sample"})


def test_backfill_writes_every_past_day_with_a_log_and_leaves_the_rest(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    days_dir = tmp_path / "days"
    for day in ("2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"):
        write_log(log, day)
    days_dir.mkdir()
    (days_dir / "2026-11-13.md").write_text("my own notes")
    (tmp_path / "focus_log" / "notes.jsonl").write_text("{}\n")

    written = write_missing_pages(log, days_dir, at(12, 0, day=15))

    assert written == ["2026-11-12", "2026-11-14"]
    assert (days_dir / "2026-11-13.md").read_text() == "my own notes", "a page is never written over"
    assert not (days_dir / "2026-11-15.md").exists(), "today isn't over yet"
    assert read_page_totals((days_dir / "2026-11-12.md").read_text())["focus_minutes"] == 10
    assert list(days_dir.glob("*.tmp")) == []
    assert write_missing_pages(log, days_dir, at(12, 0, day=15)) == []


def test_the_midnight_write_adds_the_day_that_just_ended(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    days_dir = tmp_path / "days"
    write_log(log, DAY, hour=22)
    assert write_missing_pages(log, days_dir, at(23, 59)) == []
    assert write_missing_pages(log, days_dir, at(0, 0, day=15) + 5) == [DAY]
    assert (days_dir / f"{DAY}.md").exists()


def test_seconds_until_midnight():
    assert find_seconds_until_midnight(at(23, 59)) == pytest.approx(60)
    assert find_seconds_until_midnight(at(0, 0)) == pytest.approx(24 * 3600, abs=3600), "a DST night is 23 or 25 hours"


def test_a_month_reads_only_its_own_pages(tmp_path):
    (tmp_path / "2026-11-02.md").write_text(build_day_page(SAMPLE_DAY, DAY).replace(DAY, "2026-11-02"))
    (tmp_path / "2026-11-14.md").write_text("no frontmatter at all")
    (tmp_path / "2026-10-31.md").write_text(SAMPLE_PAGE)
    (tmp_path / "2026-11-2.md").write_text(SAMPLE_PAGE)
    month = read_month(tmp_path, "2026-11")
    assert sorted(month) == ["2026-11-02", "2026-11-14"]
    assert month["2026-11-02"]["focus_minutes"] == 140
    assert month["2026-11-14"] == {}


def sample(hour: int, minute: int, second: int, state: str, app: str | None, site: str | None = None) -> dict:
    line = {"ts": at(hour, minute) + second, "day": DAY, "event": "sample", "state": state, "app": app, "site": site}
    return line


def test_time_per_app_and_on_youtube_only_counts_time_at_the_desk():
    lines = [line(9, 0, "state", state="working")]
    lines += [sample(9, minute, second, "working", "Cursor") for minute in range(10) for second in (0, 30)]  # 10 min
    lines += [sample(10, minute, second, "phone", "Google Chrome", "youtube.com") for minute in range(4) for second in (0, 30)]  # 4 min
    lines += [sample(10, minute, 0, "working", "Arc", "m.youtube.com") for minute in range(10, 12)]  # 1 min, another browser
    lines += [sample(10, minute, 0, "working", "Google Chrome", "github.com") for minute in range(20, 26)]  # 3 min, not YouTube
    lines += [sample(11, minute, 0, "away", "Google Chrome", "youtube.com") for minute in range(30)]  # not at the desk
    lines += [sample(12, minute, 0, "unknown", "Cursor") for minute in range(30)]  # camera down
    lines += [sample(13, minute, 0, "working", "Locked") for minute in range(30)]  # screen locked
    lines += [sample(14, minute, 0, "working", None) for minute in range(30)]  # Mac not reporting
    page = build_day_page(lines, DAY)
    assert "## Apps\n- Cursor: 10m\n- Google Chrome: 7m (YouTube 4m)\n- Arc: 1m (YouTube 1m)\n" in page, "a browser's YouTube part"
    assert "- YouTube: 5m\n" in page, "4 min in Chrome and 1 in Arc; github.com doesn't count"
    assert "youtube_minutes: 5\n" in page
    assert "github.com" not in page, "other sites aren't on the page"


def test_only_the_top_ten_apps_make_the_page():
    lines = [sample(9, index, 0, "working", f"App {index:02d}") for index in range(12) for _ in range(index + 1)]
    apps_part = build_day_page(lines, DAY).split("## Apps\n")[1]
    listed = [entry.split(":")[0].removeprefix("- ") for entry in apps_part.strip().splitlines()]
    assert listed == [f"App {index:02d}" for index in range(11, 1, -1)]


def test_an_old_log_without_apps_still_makes_a_page():
    old_lines = [
        line(9, 0, "state", state="working"),
        {**line(9, 30, "sample", state="working", person=0.9)},
    ]
    page = build_day_page(old_lines, DAY)
    assert "- Focus: 30m" in page
    assert "- YouTube: 0s" in page
    assert page.endswith("## Apps\n- None\n")


def test_paused_mac_tracking_counts_toward_no_app_and_the_page_says_how_long():
    lines = [line(9, 0, "state", state="working")]
    lines += [sample(9, minute, 30, "working", "Cursor") for minute in range(10)]  # 5 min
    lines.append(line(9, 10, "mac_tracking", enabled=False))
    lines += [sample(9, minute, 30, "working", "Google Chrome", "youtube.com") for minute in range(10, 60)]  # paused
    lines.append(line(10, 10, "mac_tracking", enabled=True))
    lines += [sample(10, minute, 30, "working", "Cursor") for minute in range(10, 14)]  # 2 min
    page = build_day_page(lines, DAY)
    apps_part = page.split("## Apps\n")[1]
    assert apps_part.startswith("Mac tracking was paused for 1h00, so that time isn't counted.\n")
    assert "Google Chrome" not in apps_part
    assert "- Cursor: 7m" in apps_part
    assert "- YouTube: 0s" in page


def test_a_pause_still_on_at_the_end_of_the_day_runs_to_the_last_line():
    lines = [line(9, 0, "state", state="working"), line(22, 0, "mac_tracking", enabled=False), line(23, 30, "sample", state="working")]
    assert "Mac tracking was paused for 1h30" in build_day_page(lines, DAY)


def test_an_old_log_without_tracking_lines_counts_as_on():
    lines = [line(9, 0, "state", state="working")] + [sample(9, minute, 0, "working", "Arc", "youtube.com") for minute in range(4)]
    page = build_day_page(lines, DAY)
    assert "paused" not in page
    assert "- Arc: 2m" in page
    assert "- YouTube: 2m" in page


def count(lines: list[dict]) -> dict[str, tuple[float, float, bool]]:
    counted = count_app_seconds(lines, DAY)
    return {app: (seconds.total, seconds.youtube, seconds.has_site) for app, seconds in counted.items()}


def test_the_shared_counter_splits_a_browser_into_youtube_and_the_rest():
    lines = [sample(9, 0, 0, "working", "Chrome", "youtube.com")] * 2  # 1 min
    lines += [sample(9, 5, 0, "phone", "Chrome", "m.youtube.com")]  # 30 s, a subdomain
    lines += [sample(9, 10, 0, "working", "Chrome", "github.com")] * 3  # 1.5 min
    lines += [sample(9, 15, 0, "working", "Chrome", None)]  # a browser sample with no site: other
    lines += [sample(9, 20, 0, "working", "Cursor")] * 4
    assert count(lines) == {"Chrome": (210, 90, True), "Cursor": (120, 0, False)}


def test_the_shared_counter_skips_away_unknown_locked_and_paused_time():
    lines = [sample(9, 0, 0, "away", "Cursor"), sample(9, 1, 0, "unknown", "Cursor"), sample(9, 2, 0, "working", "Locked")]
    lines += [line(9, 3, "mac_tracking", enabled=False), sample(9, 4, 0, "working", "Cursor"), line(9, 5, "mac_tracking", enabled=True)]
    lines += [sample(9, 6, 0, "working", "Cursor")]
    assert count(lines) == {"Cursor": (30, 0, False)}


def test_the_shared_counter_reads_old_logs_without_sites_or_apps():
    old = [{"ts": at(9), "day": DAY, "event": "sample", "state": "working", "app": "Arc"}, {"ts": at(9, 1), "day": DAY, "event": "sample", "state": "working"}]
    assert count(old) == {"Arc": (30, 0, False)}


def test_a_goal_goes_on_the_page_so_the_day_keeps_it():
    page = build_day_page(SAMPLE_DAY, DAY, goal_minutes=270)
    assert "todos_done: 2\nyoutube_minutes: 0\ngoal_minutes: 270\n---" in page
    assert "- Focus: 2h20\n- Goal: 4h30\n- Phone: 10m\n" in page
    assert "- Goal: 4h\n" in build_day_page(SAMPLE_DAY, DAY, goal_minutes=240)
    assert "oal" not in build_day_page(SAMPLE_DAY, DAY), "no goal, no line"


def test_written_pages_get_the_desks_goal(tmp_path):
    log = FocusLog(tmp_path / "focus_log")
    for event in SAMPLE_DAY:
        log.write(event)
    write_missing_pages(log, tmp_path / "days", at(12, 0, day=15), goal_minutes=60)
    assert "- Goal: 1h\n" in (tmp_path / "days" / f"{DAY}.md").read_text()


def test_the_goal_is_off_or_whole_and_half_hours_from_one_to_twelve(tmp_path):
    goal = GoalSetting(tmp_path / "goal.json")
    assert goal.read() == {"minutes": None}
    accepted = [minutes for minutes in (None, 30, 60, 90, 75, 720, 750, 240.0, True, "240") if goal.accepts("minutes", minutes)]
    assert accepted == [None, 60, 90, 720]


def working(*spans: tuple[float, float]) -> list[dict]:
    """Working from start to end (hours), away in between."""
    lines = []
    for start, end in spans:
        lines += [line(int(start), round(start % 1 * 60), "state", state="working"), line(int(end), round(end % 1 * 60), "state", state="away")]
    return lines


def test_studied_with_is_the_time_both_were_focused_at_once():
    mine = working((9, 11), (13, 14))
    assert count_overlap_seconds(mine, working((10, 13.5)), DAY) == 90 * 60, "1 h of my morning, 30 min of my afternoon"
    assert count_overlap_seconds(mine, working((11, 13)), DAY) == 0, "touching isn't together"
    assert count_overlap_seconds(mine, working((8, 15)), DAY) == 3 * 3600, "never more than my own"
    assert count_overlap_seconds(mine, working((9.5, 9.75), (10, 10.5), (13.25, 13.5)), DAY) == 60 * 60
    assert count_overlap_seconds(mine, [], DAY) == 0
    phone = [line(10, 0, "state", state="phone"), line(12, 0, "state", state="away")]
    assert count_overlap_seconds(mine, phone, DAY) == 0, "only focused time counts"
