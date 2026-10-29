"""Reads the focus log and prints what the days looked like.

    .venv/bin/python scripts/focus_stats.py            # today
    .venv/bin/python scripts/focus_stats.py --days 7   # the last week, plus focus by hour of day

Reads data/focus_log/ (or DAYANPI_DATA_DIR/focus_log). It only looks at the log, so it
can run while the service is up.
"""

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from dayanpi.focus.tracker import DAY_FORMAT, DayReplay, DayTotals, FocusLog, Segment, find_focus_log_dir, replay_day, total_day
from dayanpi.sign.renderer import format_duration

HOURS = 24


@dataclass
class HourTotals:
    working: list[float] = field(default_factory=lambda: [0.0] * HOURS)
    phone: list[float] = field(default_factory=lambda: [0.0] * HOURS)
    pickups: list[int] = field(default_factory=lambda: [0] * HOURS)


def list_recent_days(last_day: datetime, count: int) -> list[str]:
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


def sum_hour_totals(replays: list[DayReplay]) -> HourTotals:
    totals = HourTotals()
    for replay in replays:
        for segment in replay.segments:
            add_segment_hours(totals, segment)
    return totals


def format_day_line(totals: DayTotals) -> str:
    first = "--:--" if totals.first_seen is None else datetime.fromtimestamp(totals.first_seen).strftime("%H:%M")
    line = (
        f"{totals.day}  first {first}  focus {format_duration(totals.working_seconds):>6}  "
        f"phone {format_duration(totals.phone_seconds):>6}  pickups {totals.pickups:>3}  "
        f"snacks {totals.snacks:>2}  best {format_duration(totals.longest_streak_seconds):>6}"
    )
    return line


def format_hour_table(totals: HourTotals) -> str:
    lines = ["", "focus by hour (share of the hour spent focused, over the days above):", "hour   focus  phone  pickups"]
    for hour in range(HOURS):
        busy = totals.working[hour] + totals.phone[hour]
        if busy == 0:
            continue
        bar = "#" * int(round(20 * totals.working[hour] / busy))
        lines.append(f"{hour:02d}:00  {format_duration(totals.working[hour]):>6} {format_duration(totals.phone[hour]):>6}  {totals.pickups[hour]:>5}  {bar}")
    table = "\n".join(lines)
    return table


def build_report(log: FocusLog, days: list[str]) -> str:
    replays = [replay_day(log.read_day(day), day) for day in days]
    lines = [format_day_line(total_day(replay)) for replay in replays if replay.events]
    if not lines:
        lines.append(f"No focus log lines for {days[0]}..{days[-1]} in {log.directory}")
    elif len(days) > 1:
        lines.append(format_hour_table(sum_hour_totals(replays)))
    report = "\n".join(lines)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Print focus totals from the log.")
    parser.add_argument("--days", type=int, default=1, help="how many days back to show (default 1 = today)")
    parser.add_argument("--log-dir", type=Path, default=find_focus_log_dir(), help="where the focus_log folder is (default: DAYANPI_DATA_DIR/focus_log, or data/focus_log)")
    args = parser.parse_args()
    log = FocusLog(args.log_dir)
    print(build_report(log, list_recent_days(datetime.now(), max(1, args.days))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
