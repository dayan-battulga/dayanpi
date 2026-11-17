"""Everyone's own desk: a focus log, a tracker, a to-do list, a Mac tracking setting and day pages per account.

A desk lives in data/users/<username>/ (DAYANPI_DATA_DIR overrides data/), with focus_log/, todos.json,
days/ and mac_tracking.json in it. Usernames can't change, so neither does the folder. A removed account's
folder moves to data/users/removed/<username>-<date>/ and stays there until someone deletes it by hand, so
whoever picks that username next starts empty. The classes in tracker.py, todos.py and mac_tracking.py
don't know about desks; they just get their paths from here.
"""

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from dayanpi.focus.days import DAYS_DIR_NAME
from dayanpi.focus.mac_tracking import MAC_TRACKING_FILE, MacTrackingSetting
from dayanpi.focus.todos import TODO_FILE, TodoList
from dayanpi.focus.tracker import FOCUS_LOG_DIR_NAME, FocusLog, FocusTracker, format_day

USERS_DIR_NAME = "users"
REMOVED_DIR_NAME = "removed"
# What sat right in data/ while there was only the owner's desk; it moves into the owner's folder once.
OWNER_DATA_NAMES = (FOCUS_LOG_DIR_NAME, TODO_FILE, DAYS_DIR_NAME, MAC_TRACKING_FILE)
# The owner's name only gets stripped and lowercased (accounts.seed_owner), so this is the last check before it's a path.
FOLDER_NAME = re.compile(r"[^/\\\x00]+")

logger = logging.getLogger(__name__)


@dataclass
class Desk:
    username: str
    folder: Path
    log: FocusLog
    tracker: FocusTracker
    todos: TodoList
    mac_tracking: MacTrackingSetting

    @property
    def days_dir(self) -> Path:
        return self.folder / DAYS_DIR_NAME


def open_desk(folder: Path, username: str, now: float) -> Desk:
    log = FocusLog(folder / FOCUS_LOG_DIR_NAME)
    tracker = FocusTracker(log, started_at=now)
    mac_tracking = MacTrackingSetting(folder / MAC_TRACKING_FILE)
    if not mac_tracking.enabled:
        tracker.set_mac_tracking(False, now)
        logger.info("Mac tracking is paused for %s (switched off on the dashboard)", username)
    desk = Desk(username, folder, log, tracker, TodoList(folder / TODO_FILE, log), mac_tracking)
    return desk


def find_free_path(parent: Path, stem: str) -> Path:
    """parent/stem, or stem-2, stem-3... when it's taken, so nothing is ever moved on top of something."""
    path = parent / stem
    count = 1
    while path.exists():
        count += 1
        path = parent / f"{stem}-{count}"
    return path


def move_owner_data(data_dir: Path, folder: Path) -> list[str]:
    """Moves the owner's data from right in data/ into their desk's folder, once. Returns what moved.

    If anything waiting to move is in the folder already, nothing moves and it says so in the log, so
    both copies stay put for a person to sort out. Only renames: nothing is copied or deleted, and the
    next start finds nothing left to move.
    """
    waiting = [name for name in OWNER_DATA_NAMES if (data_dir / name).exists()]
    clashes = [name for name in waiting if (folder / name).exists()]
    moved: list[str] = []
    if clashes:
        logger.error("didn't move the old data into %s: %s is in both places; nothing moved", folder, ", ".join(clashes))
    elif waiting:
        folder.mkdir(parents=True, exist_ok=True)
        for name in waiting:
            (data_dir / name).rename(folder / name)
            moved.append(name)
        logger.info("moved %s from %s into %s", ", ".join(moved), data_dir, folder)
    return moved


class Desks:
    """Every account's desk by username: opened at startup, when someone joins, or the first time it's asked for."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.users_dir = data_dir / USERS_DIR_NAME
        self._desks: dict[str, Desk] = {}
        self._lock = threading.Lock()

    def find_folder(self, username: str) -> Path:
        """Raises ValueError for a name that couldn't be one folder, or that's the removed folders' own."""
        if FOLDER_NAME.fullmatch(username) is None or username in (".", "..", REMOVED_DIR_NAME):
            raise ValueError(f"{username!r} can't be a desk's folder")
        folder = self.users_dir / username
        return folder

    def open(self, username: str, now: float) -> Desk:
        with self._lock:
            desk = self._desks.get(username)
            if desk is None:
                desk = open_desk(self.find_folder(username), username, now)
                self._desks[username] = desk
        return desk

    def list(self) -> list[Desk]:
        with self._lock:
            listed = list(self._desks.values())
        return listed

    def remove(self, username: str, now: float) -> Path | None:
        """Closes the desk and moves its folder to removed/<username>-<date>/, never on top of another one.

        Returns where it went, or None when the account never wrote anything. Raises OSError if the move fails.
        ponytail: a request of theirs already past the sign-in check could still write a fresh folder of that name
        a moment after; their sessions are gone, so nothing more follows it. Lock per desk if that ever matters.
        """
        with self._lock:
            self._desks.pop(username, None)
            folder = self.find_folder(username)
            moved = None
            if folder.exists():
                moved = find_free_path(self.users_dir / REMOVED_DIR_NAME, f"{username}-{format_day(now)}")
                moved.parent.mkdir(parents=True, exist_ok=True)
                folder.rename(moved)
        return moved
