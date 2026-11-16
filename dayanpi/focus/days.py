"""One markdown page per finished day, data/days/YYYY-MM-DD.md, for the calendar card and for reading anywhere.

Each page is built from that day's focus log: the totals (the same replay as the restart
and the stats tool), the work blocks, the to-dos checked off, and the sites the Mac had in
front while you were at the desk. The numbers also go in
the frontmatter, which Obsidian shows as properties and the calendar reads back. Pages are
written once: at startup for every past day that has a log and no page, then just after
each local midnight. Today never gets a file; the routes build its page live from the log.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from dayanpi.focus.tracker import DAY_FORMAT, SAMPLE_LOG_INTERVAL_S, FocusLog, find_data_dir, format_day, replay_day, total_day
from dayanpi.sign.renderer import format_duration
from dayanpi.utils.files import write_atomically

DAYS_DIR_NAME = "days"
DAY_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
MONTH_PATTERN = r"^\d{4}-\d{2}$"
TOP_SITES = 10
AT_DESK_STATES = ("working", "phone")
LOCKED_APP = "Locked"


def find_days_dir() -> Path:
    path = find_data_dir() / DAYS_DIR_NAME
    return path


@dataclass
class Block:
    start: float
    end: float
    still_on: bool = False  # never stopped that day: ran past midnight, or the Pi went down


def list_day_lines(lines: list[dict], day: str) -> list[dict]:
    todays = sorted((line for line in lines if line.get("day") == day and "ts" in line), key=lambda line: line["ts"])
    return todays


def find_blocks(lines: list[dict], day: str) -> list[Block]:
    """The day's work blocks. One carried over from the day before starts at midnight; one never stopped ends at the day's last line."""
    todays = list_day_lines(lines, day)
    blocks = []
    started = None
    for line in todays:
        if line.get("event") == "block" and line.get("action") == "start" and started is None:
            started = line["ts"]
        elif line.get("event") == "block" and line.get("action") == "stop":
            blocks.append(Block(start=started if started is not None else read_midnight(day), end=line["ts"]))
            started = None
    if started is not None:
        blocks.append(Block(start=started, end=todays[-1]["ts"], still_on=True))
    return blocks


def find_finished_todos(lines: list[dict], day: str) -> list[dict]:
    """The to-dos checked off that day and still checked at the end of it, in the order they were finished."""
    finished = {}
    for line in list_day_lines(lines, day):
        if line.get("event") == "todo" and line.get("action") in ("done", "undone"):
            finished.pop(line.get("id"), None)  # re-checked later moves to the end
            if line["action"] == "done":
                finished[line.get("id")] = line
    todos = list(finished.values())
    return todos


def count_site_seconds(lines: list[dict], day: str) -> dict[str, float]:
    """The TOP_SITES sites by time at the desk, most first.

    From the sample lines: each one stands for the SAMPLE_LOG_INTERVAL_S before it, and
    counts when you were working or on your phone (not away or unknown), the Mac wasn't
    locked, and Mac tracking wasn't paused. Older logs have no site on their samples and
    count nothing.
    """
    totals: dict[str, float] = {}
    paused = False
    for line in list_day_lines(lines, day):
        site = line.get("site")
        if line.get("event") == "mac_tracking":
            paused = line.get("enabled") is False
        if line.get("event") == "sample" and site and not paused and line.get("state") in AT_DESK_STATES and line.get("app") != LOCKED_APP:
            totals[site] = totals.get(site, 0.0) + SAMPLE_LOG_INTERVAL_S
    top = dict(sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:TOP_SITES])
    return top


def count_paused_seconds(lines: list[dict], day: str) -> float:
    """How long Mac tracking was switched off that day, from its mac_tracking lines.

    A pause still on at the end of the day runs to the day's last line. Older logs have no
    such lines, so they were never paused.
    """
    todays = list_day_lines(lines, day)
    paused = 0.0
    paused_since = None
    for line in todays:
        if line.get("event") == "mac_tracking" and line.get("enabled") is False and paused_since is None:
            paused_since = line["ts"]
        elif line.get("event") == "mac_tracking" and line.get("enabled") is True and paused_since is not None:
            paused += line["ts"] - paused_since
            paused_since = None
    if paused_since is not None:
        paused += todays[-1]["ts"] - paused_since
    return paused


def read_midnight(day: str) -> float:
    midnight = datetime.strptime(day, DAY_FORMAT).timestamp()
    return midnight


def format_clock(moment: float) -> str:
    clock = datetime.fromtimestamp(moment).strftime("%H:%M")
    return clock


def count_minutes(seconds: float) -> int:
    minutes = round(seconds / 60)
    return minutes


def build_day_page(lines: list[dict], day: str) -> str:
    replay = replay_day(lines, day)
    totals = total_day(replay)
    blocks = find_blocks(lines, day)
    todos = find_finished_todos(lines, day)
    sites = count_site_seconds(lines, day)
    paused = count_paused_seconds(lines, day)
    date = datetime.strptime(day, DAY_FORMAT)
    parts = [
        "---",
        f"date: {day}",
        f"focus_minutes: {count_minutes(totals.working_seconds)}",
        f"phone_minutes: {count_minutes(totals.phone_seconds)}",
        f"away_minutes: {count_minutes(totals.away_seconds)}",
        f"pickups: {totals.pickups}",
        f"best_streak_minutes: {count_minutes(totals.longest_streak_seconds)}",
        f"blocks: {len(blocks)}",
        f"todos_done: {len(todos)}",
        "---",
        "",
        f"# {date:%A}, {date:%B} {date.day}, {date.year}",
        "",
    ]
    if replay.events == 0:
        parts.append("Nothing was logged on this day.")
    else:
        parts += [
            "## Totals",
            f"- Focus: {format_duration(totals.working_seconds)}",
            f"- Phone: {format_duration(totals.phone_seconds)}",
            f"- Away: {format_duration(totals.away_seconds)}",
            f"- Pickups: {totals.pickups}",
            f"- Best streak: {format_duration(totals.longest_streak_seconds)}",
            "",
            "## Focus blocks",
            *[
                f"- {format_clock(block.start)}–{format_clock(block.end)} ({format_duration(block.end - block.start)})"
                + (", still on at the end of the day" if block.still_on else "")
                for block in blocks
            ],
            *([] if blocks else ["- None"]),
            "",
            "## To-dos done",
            *[f"- {' '.join(str(todo.get('text', '')).split())} ({format_duration(todo.get('seconds', 0))})" for todo in todos],
            *([] if todos else ["- None"]),
            "",
            "## Sites",
            *([f"Mac tracking was paused for {format_duration(paused)}, so that time isn't counted."] if paused > 0 else []),
            *[f"- {site}: {format_duration(seconds)}" for site, seconds in sites.items()],
            *([] if sites else ["- None"]),
        ]
    page = "\n".join(parts) + "\n"
    return page


def read_page_totals(page: str) -> dict:
    """The whole numbers in a page's frontmatter, the lines between the first two ---."""
    totals = {}
    lines = page.splitlines()
    if lines and lines[0] == "---":
        for line in lines[1:]:
            if line == "---":
                break
            key, _, value = line.partition(":")
            if value.strip().isdigit():
                totals[key.strip()] = int(value)
    return totals


def list_logged_days(log: FocusLog) -> list[str]:
    days = sorted(path.stem for path in log.directory.glob("*.jsonl") if re.fullmatch(DAY_PATTERN, path.stem))
    return days


def write_missing_pages(log: FocusLog, days_dir: Path, now: float) -> list[str]:
    """Writes a page for every day before today that has a log and no page yet. Returns the days written."""
    today = format_day(now)
    written = []
    for day in list_logged_days(log):
        path = days_dir / f"{day}.md"
        if day < today and not path.exists():
            write_atomically(path, build_day_page(log.read_day(day), day))
            written.append(day)
    return written


def read_month(days_dir: Path, month: str) -> dict[str, dict]:
    """Each written day of the month (YYYY-MM) and the numbers from its page."""
    month_days = {
        path.stem: read_page_totals(path.read_text(encoding="utf-8"))
        for path in sorted(days_dir.glob(f"{month}-*.md"))
        if re.fullmatch(DAY_PATTERN, path.stem)
    }
    return month_days


def find_seconds_until_midnight(now: float) -> float:
    moment = datetime.fromtimestamp(now)
    midnight = datetime.combine(moment.date() + timedelta(days=1), datetime.min.time())
    seconds = midnight.timestamp() - now
    return seconds
