"""One markdown page per finished day, days/YYYY-MM-DD.md in each desk's folder, for the calendar and for reading anywhere.

Each page is built from that day's focus log: the totals (the same replay as the restart
and the stats tool), the to-dos checked off, the apps the Mac had in front while you were at
the desk (each browser's YouTube part too), the time on YouTube, and the day's focus goal if there was one
(Settings → Profile, the desk's goal.json). The numbers also go in
the frontmatter, which Obsidian shows as properties and the calendar reads back. Pages are
written once: at startup for every past day that has a log and no page, then just after
each local midnight. Today never gets a file; the routes build its page live from the log.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from dayanpi.focus.tracker import DAY_FORMAT, SAMPLE_LOG_INTERVAL_S, FocusLog, Segment, format_day, format_duration, replay_day, total_day
from dayanpi.utils.files import JsonSetting, write_atomically

DAYS_DIR_NAME = "days"
DAY_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
MONTH_PATTERN = r"^\d{4}-\d{2}$"
TOP_APPS = 10
CHART_APPS = 8  # /api/apps names this many apps, the rest are summed
TOP_SITES = 5  # someone's desk lists this many of today's sites
OTHER_APPS = "Other apps"
WEEK_DAYS = 7
YOUTUBE = "youtube.com"  # and its subdomains (m., music.), in any browser; the only site the day page counts
AT_DESK_STATES = ("working", "phone")
LOCKED_APP = "Locked"
GOAL_FILE = "goal.json"  # {"minutes": null | 60..720}: the desk's daily focus goal, off until picked
GOAL_MIN_MINUTES = 60
GOAL_MAX_MINUTES = 12 * 60
GOAL_STEP_MINUTES = 30
STUDIED_WITH_MIN_S = 5 * 60  # focused at the same time at least this long to count as studying together


class GoalSetting(JsonSetting):
    """read()["minutes"]: the daily focus goal in minutes, or None for off."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, {"minutes": None})

    def accepts(self, key: str, value: object) -> bool:
        accepted = value is None or (
            type(value) is int and GOAL_MIN_MINUTES <= value <= GOAL_MAX_MINUTES and value % GOAL_STEP_MINUTES == 0
        )
        return accepted


def list_day_lines(lines: list[dict], day: str) -> list[dict]:
    todays = sorted((line for line in lines if line.get("day") == day and "ts" in line), key=lambda line: line["ts"])
    return todays


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


def is_youtube(site: str | None) -> bool:
    youtube = site is not None and (site == YOUTUBE or site.endswith("." + YOUTUBE))
    return youtube


@dataclass
class AppSeconds:
    total: float = 0.0
    youtube: float = 0.0  # of total, with YouTube in front (any browser)
    has_site: bool = False  # a sample named a site, so the app is a browser


def list_counted_samples(lines: list[dict], day: str) -> list[dict]:
    """The sample lines that count toward the Mac's time, each standing for the SAMPLE_LOG_INTERVAL_S before it: you were
    working or on your phone (not away or unknown), the Mac wasn't locked, and Mac tracking wasn't paused. Older logs
    without an app on their samples count nothing."""
    counted = []
    paused = False
    for line in list_day_lines(lines, day):
        app = line.get("app")
        if line.get("event") == "mac_tracking":
            paused = line.get("enabled") is False
        if line.get("event") == "sample" and app and not paused and line.get("state") in AT_DESK_STATES and app != LOCKED_APP:
            counted.append(line)
    return counted


def count_app_seconds(lines: list[dict], day: str) -> dict[str, AppSeconds]:
    """Seconds per Mac app (every app, no cutoff) while you were at the desk. The day page and /api/apps both use this.
    Without a site, all the time is plain app time."""
    apps: dict[str, AppSeconds] = {}
    for line in list_counted_samples(lines, day):
        counted = apps.setdefault(line["app"], AppSeconds())
        counted.total += SAMPLE_LOG_INTERVAL_S
        counted.youtube += SAMPLE_LOG_INTERVAL_S if is_youtube(line.get("site")) else 0.0
        counted.has_site = counted.has_site or bool(line.get("site"))
    return apps


def build_sites_chart(log: FocusLog, now: float) -> list[dict]:
    """Today's TOP_SITES sites by seconds in front, most first, from the same samples as the apps."""
    today = format_day(now)
    sites: dict[str, float] = {}
    for line in list_counted_samples(log.read_day(today), today):
        if line.get("site"):
            sites[line["site"]] = sites.get(line["site"], 0.0) + SAMPLE_LOG_INTERVAL_S
    ranked = sorted(sites, key=lambda site: (-sites[site], site))
    chart = [{"site": site, "seconds": sites[site]} for site in ranked[:TOP_SITES]]
    return chart


@dataclass
class MacTime:
    apps: dict[str, AppSeconds]  # the TOP_APPS apps by seconds, most first
    youtube: float  # seconds with YouTube in front, in any browser


def rank_apps(apps: dict[str, AppSeconds]) -> list[str]:
    """App names, most seconds first, ties by name."""
    names = sorted(apps, key=lambda app: (-apps[app].total, app))
    return names


def count_mac_seconds(lines: list[dict], day: str) -> MacTime:
    """Time per Mac app (the TOP_APPS) and on YouTube while you were at the desk. Other sites aren't counted."""
    apps = count_app_seconds(lines, day)
    top = {app: apps[app] for app in rank_apps(apps)[:TOP_APPS]}
    mac_time = MacTime(apps=top, youtube=sum(counted.youtube for counted in apps.values()))
    return mac_time


def merge_app_seconds(parts: list[dict[str, AppSeconds]]) -> dict[str, AppSeconds]:
    merged: dict[str, AppSeconds] = {}
    for part in parts:
        for app, counted in part.items():
            into = merged.setdefault(app, AppSeconds())
            into.total += counted.total
            into.youtube += counted.youtube
            into.has_site = into.has_site or counted.has_site
    return merged


def list_range_days(now: float, range_name: str) -> list[str]:
    """Local days of the range, today first. A week is the last 7 days including today."""
    today = datetime.fromtimestamp(now).date()
    count = WEEK_DAYS if range_name == "week" else 1
    range_days = [(today - timedelta(days=offset)).strftime(DAY_FORMAT) for offset in range(count)]
    return range_days


def build_apps_chart(log: FocusLog, now: float, range_name: str) -> list[dict]:
    """The Apps card's rows: the CHART_APPS biggest apps, then the rest summed as "Other apps"."""
    apps = merge_app_seconds([count_app_seconds(log.read_day(day), day) for day in list_range_days(now, range_name)])
    ranked = rank_apps(apps)
    rows = []
    for app in ranked[:CHART_APPS]:
        counted = apps[app]
        row = {"app": app, "total_seconds": counted.total}
        if counted.has_site:
            row |= {"youtube_seconds": counted.youtube, "other_sites_seconds": counted.total - counted.youtube}
        rows.append(row)
    if len(ranked) > CHART_APPS:
        rows.append({"app": OTHER_APPS, "total_seconds": sum(apps[app].total for app in ranked[CHART_APPS:])})
    return rows


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


def count_minutes(seconds: float) -> int:
    minutes = round(seconds / 60)
    return minutes


def list_working_segments(lines: list[dict], day: str) -> list[Segment]:
    working = [segment for segment in replay_day(lines, day).segments if segment.state == "working"]
    return working


def count_overlap_seconds(mine: list[dict], theirs: list[dict], day: str) -> float:
    """Seconds two desks were both focused at the same time that day, from their logs' working segments. Each desk's
    segments are in order and never overlap each other, so one walk through both lists does it."""
    ours, others = list_working_segments(mine, day), list_working_segments(theirs, day)
    overlap = 0.0
    i = j = 0
    while i < len(ours) and j < len(others):
        overlap += max(0.0, min(ours[i].end, others[j].end) - max(ours[i].start, others[j].start))
        if ours[i].end < others[j].end:
            i += 1
        else:
            j += 1
    return overlap


def format_goal(minutes: int) -> str:
    """"4h" or "4h30": a goal is whole or half hours."""
    goal = format_duration(minutes * 60).removesuffix("00")
    return goal


def describe_app_time(counted: AppSeconds) -> str:
    """"1h41", and a browser's YouTube part after it: "1h41 (YouTube 22m)"."""
    described = format_duration(counted.total) + (f" (YouTube {format_duration(counted.youtube)})" if counted.youtube > 0 else "")
    return described


def build_day_page(lines: list[dict], day: str, goal_minutes: int | None = None) -> str:
    replay = replay_day(lines, day)
    totals = total_day(replay)
    todos = find_finished_todos(lines, day)
    mac_time = count_mac_seconds(lines, day)
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
        f"todos_done: {len(todos)}",
        f"youtube_minutes: {count_minutes(mac_time.youtube)}",
        *([] if goal_minutes is None else [f"goal_minutes: {goal_minutes}"]),
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
            *([] if goal_minutes is None else [f"- Goal: {format_goal(goal_minutes)}"]),
            f"- Phone: {format_duration(totals.phone_seconds)}",
            f"- Away: {format_duration(totals.away_seconds)}",
            f"- Pickups: {totals.pickups}",
            f"- Best streak: {format_duration(totals.longest_streak_seconds)}",
            f"- YouTube: {format_duration(mac_time.youtube)}",
            "",
            "## To-dos done",
            *[f"- {' '.join(str(todo.get('text', '')).split())} ({format_duration(todo.get('seconds', 0))})" for todo in todos],
            *([] if todos else ["- None"]),
            "",
            "## Apps",
            *([f"Mac tracking was paused for {format_duration(paused)}, so that time isn't counted."] if paused > 0 else []),
            *[f"- {app}: {describe_app_time(counted)}" for app, counted in mac_time.apps.items()],
            *([] if mac_time.apps else ["- None"]),
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


def write_missing_pages(log: FocusLog, days_dir: Path, now: float, goal_minutes: int | None = None) -> list[str]:
    """Writes a page for every day before today that has a log and no page yet, with the goal as it is now. Returns the
    days written."""
    # ponytail: the goal at write time, which is the day's own since pages get written just after midnight; a page
    # written late (the Pi off over midnight) takes the newer goal. Log goal changes if that ever matters.
    today = format_day(now)
    written = []
    for day in list_logged_days(log):
        path = days_dir / f"{day}.md"
        if day < today and not path.exists():
            write_atomically(path, build_day_page(log.read_day(day), day, goal_minutes))
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


def read_focus_minutes(days_dir: Path) -> dict[str, int]:
    """Every written day's focused minutes, from its page, oldest first."""
    minutes = {
        path.stem: read_page_totals(path.read_text(encoding="utf-8")).get("focus_minutes", 0)
        for path in sorted(days_dir.glob("*.md"))
        if re.fullmatch(DAY_PATTERN, path.stem)
    }
    return minutes


def find_seconds_until_midnight(now: float) -> float:
    moment = datetime.fromtimestamp(now)
    midnight = datetime.combine(moment.date() + timedelta(days=1), datetime.min.time())
    seconds = midnight.timestamp() - now
    return seconds
