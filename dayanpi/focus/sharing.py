"""What each person shows the room (Settings → Share with the room), and the one function that builds it.

Each desk keeps its switches in its folder's sharing.json, {"focus": true, "todos": true, ...}, saved whole on every
change. Status (the state and its timer) always shows. Focus time, the to-do list and history start on; apps, sites
and video start off, and sites only count while apps is on. A missing key means its default, and a file that can't
be read means all the defaults, with one warning.

build_seat() is the only thing that decides what of a desk leaves the Pi for anyone else, so everything that shows
another person's data goes through it, and a part that's switched off is never in what it returns. Your own desk
(the stream's "focus" and the desk routes) always shows you everything.
"""

import json
import logging
import threading
from pathlib import Path

from dayanpi.utils.files import write_atomically

SHARING_FILE = "sharing.json"
# History and video have nothing to show yet: their desk page and the video come later, and read these then.
DEFAULT_SHARING = {"focus": True, "todos": True, "history": True, "apps": False, "sites": False, "video": False}
HERE_S = 120.0  # someone is here while their site is open or their camera checked them this recently

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


def is_here(seen_at: float | None, status: dict, now: float) -> bool:
    """The site open (seen_at, from the stream) or a check with a frame within HERE_S."""
    checked_at = None if status["last_check"] is None else status["last_check"]["at"]
    here = any(at is not None and now - at < HERE_S for at in (seen_at, checked_at))
    return here


def build_seat(username: str, name: str, status: dict, sharing: dict[str, bool], here: bool) -> dict:
    """What the room sees of one desk: who and how they are, always, and each other part only while its switch is on.

    status is the desk's own full focus status (app.build_desk_status); nothing else of it ever leaves through here.
    """
    seat = {
        "username": username,
        "name": name,
        "here": here,
        "state": status["state"] if here else "offline",
        "seconds_in_state": status["seconds_in_state"] if here else None,
    }
    if sharing["focus"]:
        seat["focus_seconds"] = status["today"]["working_seconds"]
    if sharing["todos"]:
        todos = status["todos"]
        current = next((item["text"] for item in todos["open"] if item["id"] == todos["current"]), None)
        seat["todos"] = {"current": current, "done": len(todos["done"]), "total": len(todos["open"]) + len(todos["done"])}
    if sharing["apps"]:
        seat["app"] = status["app"]
        if sharing["sites"]:
            seat["site"] = status["site"]
    return seat
