from datetime import datetime

import pytest

from dayanpi.focus.days import (
    build_day_page,
    find_blocks,
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
    line(9, 5, "block", action="start", source="api"),
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
blocks: 1
todos_done: 2
---

# Saturday, November 14, 2026

## Totals
- Focus: 2h20
- Phone: 10m
- Away: 30m
- Pickups: 1
- Best streak: 1h00

## Focus blocks
- 09:05–11:00 (1h55)

## To-dos done
- finish the report (1h12)
- reply to emails (10m)

## Sites
- None
"""


def test_a_sample_day_page():
    assert build_day_page(SAMPLE_DAY, DAY) == SAMPLE_PAGE


def test_a_day_with_no_todos_or_blocks_says_none():
    page = build_day_page([line(9, 0, "state", state="working"), line(9, 30, "sample")], DAY)
    assert "## Focus blocks\n- None\n\n## To-dos done\n- None\n" in page
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
        "blocks": 0,
        "todos_done": 0,
    }


def test_blocks_that_cross_midnight_are_cut_at_the_day_edges():
    lines = [line(0, 30, "block", action="stop"), line(23, 0, "block", action="start"), line(23, 40, "sample")]
    blocks = find_blocks(lines, DAY)
    assert [(block.start, block.end, block.still_on) for block in blocks] == [
        (at(0, 0), at(0, 30), False),
        (at(23, 0), at(23, 40), True),
    ]
    assert "- 23:00–23:40 (40m), still on at the end of the day" in build_day_page(lines, DAY)


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


def test_minutes_per_site_only_count_time_at_the_desk():
    lines = [line(9, 0, "state", state="working")]
    lines += [sample(9, minute, second, "working", "Google Chrome", "github.com") for minute in range(10) for second in (0, 30)]  # 10 min
    lines += [sample(10, minute, second, "phone", "Google Chrome", "youtube.com") for minute in range(4) for second in (0, 30)]  # 4 min
    lines += [sample(11, minute, 0, "away", "Google Chrome", "youtube.com") for minute in range(30)]  # not at the desk
    lines += [sample(12, minute, 0, "unknown", "Google Chrome", "youtube.com") for minute in range(30)]  # camera down
    lines += [sample(13, minute, 0, "working", "Locked", "youtube.com") for minute in range(30)]  # screen locked
    lines += [sample(14, minute, 0, "working", "Code") for minute in range(30)]  # no site
    page = build_day_page(lines, DAY)
    assert "## Sites\n- github.com: 10m\n- youtube.com: 4m\n" in page


def test_only_the_top_ten_sites_make_the_page():
    lines = [sample(9, index, 0, "working", "Arc", f"site{index:02d}.com") for index in range(12) for _ in range(index + 1)]
    sites_part = build_day_page(lines, DAY).split("## Sites\n")[1]
    listed = [entry.split(":")[0].removeprefix("- ") for entry in sites_part.strip().splitlines()]
    assert listed == [f"site{index:02d}.com" for index in range(11, 1, -1)]


def test_an_old_log_without_sites_still_makes_a_page():
    old_lines = [
        line(9, 0, "state", state="working"),
        line(9, 0, "mac_app", app="Google Chrome"),
        {**line(9, 30, "sample", state="working", app="Google Chrome", person=0.9)},
    ]
    page = build_day_page(old_lines, DAY)
    assert "- Focus: 30m" in page
    assert page.endswith("## Sites\n- None\n")


def test_paused_mac_tracking_counts_toward_no_site_and_the_page_says_how_long():
    lines = [line(9, 0, "state", state="working")]
    lines += [sample(9, minute, 30, "working", "Google Chrome", "github.com") for minute in range(10)]  # 5 min
    lines.append(line(9, 10, "mac_tracking", enabled=False))
    lines += [sample(9, minute, 30, "working", "Google Chrome", "youtube.com") for minute in range(10, 60)]  # paused
    lines.append(line(10, 10, "mac_tracking", enabled=True))
    lines += [sample(10, minute, 30, "working", "Google Chrome", "github.com") for minute in range(10, 14)]  # 2 min
    page = build_day_page(lines, DAY)
    sites_part = page.split("## Sites\n")[1]
    assert sites_part.startswith("Mac tracking was paused for 1h00, so that time isn't counted.\n")
    assert "youtube.com" not in sites_part
    assert "- github.com: 7m" in sites_part


def test_a_pause_still_on_at_the_end_of_the_day_runs_to_the_last_line():
    lines = [line(9, 0, "state", state="working"), line(22, 0, "mac_tracking", enabled=False), line(23, 30, "sample", state="working")]
    assert "Mac tracking was paused for 1h30" in build_day_page(lines, DAY)


def test_an_old_log_without_tracking_lines_counts_as_on():
    lines = [line(9, 0, "state", state="working")] + [sample(9, minute, 0, "working", "Arc", "github.com") for minute in range(4)]
    page = build_day_page(lines, DAY)
    assert "paused" not in page
    assert "- github.com: 2m" in page
