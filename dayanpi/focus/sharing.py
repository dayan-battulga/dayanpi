"""What each person shows the room (Settings → Share with the room), and the one gate everything else goes through.

Each desk keeps its switches in its folder's sharing.json, {"focus": true, "todos": true, ...}, saved whole on every
change. Status (the state and its timer) always shows. Focus time, the to-do list, history and nudges start on; apps,
sites and video start off, and sites only count while apps is on. A missing key means its default, and a file that
can't be read means all the defaults, with one warning.

share_parts() is the only thing that decides what of a desk leaves the Pi for anyone else: every part of a seat,
their desk page and the group calendar is named in NEEDS with the switches it needs, and a part whose switches
aren't all on is never even made, let alone sent. Your own desk (the stream's "focus" and the desk routes) always
shows you everything.
"""

import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from dayanpi.utils.files import write_atomically

SHARING_FILE = "sharing.json"
# Nudges isn't something you show; it's whether others may nudge you. Video waits for step 7.
DEFAULT_SHARING = {"focus": True, "todos": True, "history": True, "apps": False, "sites": False, "video": False, "nudges": True}
SHOWN_SWITCHES = ("focus", "todos", "apps", "sites", "video", "history")  # what "Sam shares ..." lists, in its order
HERE_S = 120.0  # someone is here while their site is open or their camera checked them this recently
NUDGE_AFTER_S = 5 * 60  # on the phone this long before anyone can nudge them
NUDGE_EVERY_S = 10 * 60  # at most one nudge per person this often
PICTURE_MAX_AGE_S = 3.0  # a seat's picture older than this is no picture
AT_DESK_STATES = ("working", "phone")  # the only states with a picture; away or unknown never has one

# Every part that can leave the Pi about someone, and the switches it needs. A part missing here is a KeyError, so
# nothing new gets out without saying what it needs.
NEEDS = {
    # The seat, in the room stream every second. Status always shows.
    "username": (),
    "name": (),
    "here": (),
    "state": (),
    "seconds_in_state": (),
    "shares": (),
    "focus_seconds": ("focus",),
    "todos": ("todos",),
    "app": ("apps",),
    "site": ("apps", "sites"),
    "nudge": ("nudges",),
    "picture": ("video",),  # the seat's say-so ({at}); the JPEG itself goes through the same part (app.their_picture)
    # Their desk (/api/people/<username>) and the quick peek, on top of the seat. When they got here is status too.
    "here_since": (),
    "today": ("focus",),
    "todo_list": ("todos",),
    "apps": ("apps",),
    "app_youtube": ("apps", "sites"),
    "sites": ("apps", "sites"),
    "history": ("history",),
    "video": ("video",),
    # The group line in the day page dialog.
    "day_focus": ("focus", "history"),
}

logger = logging.getLogger(__name__)


class SharingSetting:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._parts = self._load()

    def read(self) -> dict[str, bool]:
        with self._lock:
            parts = dict(self._parts)
        return parts

    def set(self, changes: dict[str, bool]) -> dict[str, bool]:
        """Changes the switches given and saves them all. A failed save is logged; the change holds until the next restart."""
        with self._lock:
            self._parts.update({key: value for key, value in changes.items() if key in DEFAULT_SHARING})
            parts = dict(self._parts)
            try:
                write_atomically(self._path, json.dumps(parts))
            except OSError:
                logger.exception("sharing setting save failed: %s", self._path)
        return parts

    def _load(self) -> dict[str, bool]:
        parts = dict(DEFAULT_SHARING)
        try:
            saved = json.loads(self._path.read_text(encoding="utf-8"))
            parts.update({key: value for key, value in saved.items() if key in DEFAULT_SHARING and isinstance(value, bool)})
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            logger.warning("couldn't read %s, so the room sees the defaults", self._path)
        return parts


def share_parts(sharing: dict[str, bool], parts: dict[str, Callable[[], object]]) -> dict:
    """The gate: each part made and kept only if every switch it needs is on. The rest are never called."""
    shared = {key: make() for key, make in parts.items() if all(sharing[switch] for switch in NEEDS[key])}
    return shared


def list_shares(sharing: dict[str, bool]) -> list[str]:
    """What they show, for "Sam shares ..." and for pages to notice a piece turning on or off. Sites need apps."""
    shares = [switch for switch in SHOWN_SWITCHES if sharing[switch] and (switch != "sites" or sharing["apps"])]
    return shares


def is_here(seen_at: float | None, status: dict, now: float) -> bool:
    """The site open (seen_at, from the stream) or a check with a frame within HERE_S."""
    checked_at = None if status["last_check"] is None else status["last_check"]["at"]
    here = any(at is not None and now - at < HERE_S for at in (seen_at, checked_at))
    return here


def describe_nudge(nudged: dict | None, now: float) -> dict:
    """How long until they can be nudged again (0 now), and how long ago the last one was, for its ripples."""
    at = None if nudged is None else nudged["at"]
    described = {
        "wait_s": 0.0 if at is None else round(max(0.0, at + NUDGE_EVERY_S - now), 1),
        "age_s": None if at is None else round(now - at, 1),
    }
    return described


def find_fresh_picture(picture: dict | None, status: dict, here: bool, now: float) -> dict | None:
    """The desk's picture ({jpeg, at}) while it's no older than PICTURE_MAX_AGE_S and they're here at the desk."""
    fresh = picture if picture is not None and here and status["state"] in AT_DESK_STATES and now - picture["at"] <= PICTURE_MAX_AGE_S else None
    return fresh


def summarize_todos(todos: dict) -> dict:
    current = next((item for item in todos["open"] if item["id"] == todos["current"]), None)
    summary = {
        "current": None if current is None else current["text"],
        "current_seconds": None if current is None else current["seconds"],
        "done": len(todos["done"]),
        "total": len(todos["open"]) + len(todos["done"]),
    }
    return summary


def build_seat(
    username: str, name: str, status: dict, sharing: dict[str, bool], here: bool, nudged: dict | None = None, now: float = 0.0, picture: dict | None = None
) -> dict:
    """What the room sees of one desk every second. status is the desk's own full focus status (app.build_desk_status)."""
    fresh = find_fresh_picture(picture, status, here, now)
    seat = share_parts(
        sharing,
        {
            "username": lambda: username,
            "name": lambda: name,
            "here": lambda: here,
            "state": lambda: status["state"] if here else "offline",
            "seconds_in_state": lambda: status["seconds_in_state"] if here else None,
            "shares": lambda: list_shares(sharing),
            "focus_seconds": lambda: status["today"]["working_seconds"],
            "todos": lambda: summarize_todos(status["todos"]),
            "app": lambda: status["app"],
            "site": lambda: status["site"],
            "nudge": lambda: describe_nudge(nudged, now),
            "picture": lambda: None if fresh is None else {"at": fresh["at"]},
        },
    )
    return seat


def can_nudge(seat: dict) -> bool:
    """On the phone NUDGE_AFTER_S or more, taking nudges, and not nudged in the last NUDGE_EVERY_S."""
    nudge = seat.get("nudge")
    allowed = nudge is not None and nudge["wait_s"] == 0 and seat["state"] == "phone" and (seat["seconds_in_state"] or 0) >= NUDGE_AFTER_S
    return allowed
