"""Reads the focus log and prints what the days looked like.

    .venv/bin/python focus_stats.py            # today
    .venv/bin/python focus_stats.py --days 7   # the last week, plus focus by hour of day

Reads data/focus_log/ (or DAYANPI_DATA_DIR/focus_log). It only looks at the log, so it
can run while the service is up.
"""

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from focus import DAY_FORMAT, DayTotals, FocusLog, Segment, replay_day, total_day

DEFAULT_LOG_DIR = Path(os.environ.get("DAYANPI_DATA_DIR", str(Path(__file__).resolve().parent / "data"))) / "focus_log"
HOURS = 24


@dataclass
class HourTotals:
    working: list[float] = field(default_factory=lambda: [0.0] * HOURS)
    phone: list[float] = field(default_factory=lambda: [0.0] * HOURS)
    pickups: list[int] = field(default_factory=lambda: [0] * HOURS)


def format_short(seconds: float) -> str:
    whole = int(round(seconds))
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    if whole < 60:
        text = f"{whole}s"
    elif hours == 0:
        text = f"{minutes}m"
    else:
        text = f"{hours}h{minutes:02d}"
    return text


def recent_days(last_day: datetime, count: int) -> list[str]:
    days = [(last_day - timedelta(days=offset)).strftime(DAY_FORMAT) for offset in range(count - 1, -1, -1)]
    return days


def add_segment_hours(totals: HourTotals, segment: Segment) -> None:
    """Splits a segment across the clock hours it touches."""
    end = segment.end if segment.end is not None else segment.start
    cursor = segment.start
    while cursor < end:
        moment = datetime.fromtimestamp(cursor)
        next_hour = (moment.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).timestamp()
        piece_end = min(end, next_hour)
        length = piece_end - cursor
        if segment.state == "working":
            totals.working[moment.hour] += length
        elif segment.state == "phone":
            totals.phone[moment.hour] += length
            if cursor == segment.start:
                totals.pickups[moment.hour] += 1
        cursor = piece_end


def hour_totals(log: FocusLog, days: list[str]) -> HourTotals:
    totals = HourTotals()
    for day in days:
        for segment in replay_day(log.read_day(day), day).segments:
            add_segment_hours(totals, segment)
    return totals


def day_line(totals: DayTotals) -> str:
    first = "--:--" if totals.first_seen is None else datetime.fromtimestamp(totals.first_seen).strftime("%H:%M")
    line = (
        f"{totals.day}  first {first}  focus {format_short(totals.working_seconds):>6}  "
        f"phone {format_short(totals.phone_seconds):>6}  pickups {totals.pickups:>3}  "
        f"snacks {totals.snacks:>2}  best {format_short(totals.longest_streak_seconds):>6}"
    )
    return line


def hour_table(totals: HourTotals) -> str:
    lines = ["", "focus by hour (share of the hour spent focused, over the days above):", "hour   focus  phone  pickups"]
    for hour in range(HOURS):
        busy = totals.working[hour] + totals.phone[hour]
        if busy == 0:
            continue
        bar = "#" * int(round(20 * totals.working[hour] / busy))
        lines.append(f"{hour:02d}:00  {format_short(totals.working[hour]):>6} {format_short(totals.phone[hour]):>6}  {totals.pickups[hour]:>5}  {bar}")
    table = "\n".join(lines)
    return table


def build_report(log: FocusLog, days: list[str]) -> str:
    lines = []
    seen_any = False
    for day in days:
        replay = replay_day(log.read_day(day), day)
        if replay.events:
            seen_any = True
            lines.append(day_line(total_day(replay)))
    if not seen_any:
        lines.append(f"No focus log lines for {days[0]}..{days[-1]} in {log.directory}")
    elif len(days) > 1:
        lines.append(hour_table(hour_totals(log, days)))
    report = "\n".join(lines)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Print focus totals from the log.")
    parser.add_argument("--days", type=int, default=1, help="how many days back to show (default 1 = today)")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR, help="where the focus_log folder is")
    args = parser.parse_args()
    log = FocusLog(args.log_dir)
    print(build_report(log, recent_days(datetime.now(), max(1, args.days))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
