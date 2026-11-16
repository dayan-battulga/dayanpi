"""The running to-do list: one list that carries over between focus blocks and days.

It lives in data/todos.json (DAYANPI_DATA_DIR overrides data/). Every save writes a new
file and swaps it in with os.replace, so a power cut leaves the old list or the new one,
never half of one. The current item collects the seconds spent working during a block.
Checked items stay in Done until local midnight, then leave the list; their "done" lines
in the focus log are what's left of them.
"""

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from dayanpi.focus.tracker import MAX_STEP_S, FocusLog, find_data_dir, format_day

TODO_FILE = "todos.json"
TEXT_MAX = 200
SAVE_EVERY_S = 30.0  # collected time saves this often, like the log's samples; edits save right away
SPOKEN_MAX = 5  # describe_todos reads this many, then says how many more

logger = logging.getLogger(__name__)


def find_todo_path() -> Path:
    path = find_data_dir() / TODO_FILE
    return path


@dataclass
class TodoItem:
    id: str
    text: str
    created_at: float
    done_at: float | None = None
    seconds: float = 0.0


def describe_item(item: TodoItem) -> dict:
    described = {"id": item.id, "text": item.text, "seconds": round(item.seconds), "done_at": item.done_at}
    return described


def describe_todos(texts: list[str]) -> str:
    """What the peace sign says, e.g. You have 3 things to do: finish the report, reply to emails, and do laundry."""
    spoken = texts[:SPOKEN_MAX] + ([f"{len(texts) - SPOKEN_MAX} more"] if len(texts) > SPOKEN_MAX else [])
    if len(spoken) > 2:
        listed = ", ".join(spoken[:-1]) + ", and " + spoken[-1]
    else:
        listed = " and ".join(spoken)
    things = "thing" if len(texts) == 1 else "things"
    sentence = f"You have {len(texts)} {things} to do: {listed}." if texts else "Your to-do list is empty."
    return sentence


class TodoList:
    """Thread-safe: the worker's checks and the API's requests both land here."""

    def __init__(self, path: Path, log: FocusLog | None = None) -> None:
        self._path = path
        self._log = log
        self._lock = threading.Lock()
        self._items: list[TodoItem] = []
        self._current_id: str | None = None
        self._counting_since: float | None = None
        self._unsaved = False
        self._last_saved_at = 0.0
        self._load()

    # ----- public API -----

    def add(self, text: str, now: float) -> dict:
        with self._lock:
            item = TodoItem(id=uuid.uuid4().hex[:8], text=text, created_at=round(now, 3))
            self._items.append(item)
            self._write("added", item, now)
            self._save_locked(now)
            added = describe_item(item)
        return added

    def change(self, item_id: str, now: float, text: str | None = None, done: bool | None = None, current: bool | None = None) -> bool:
        """Edits, checks or unchecks an item, or makes it (or stops it being) the current one. False if there's no such item."""
        with self._lock:
            item = self._find(item_id)
            if item is not None:
                if text is not None:
                    item.text = text
                if done is not None and done != (item.done_at is not None):
                    self._set_done_locked(item, done, now)
                if current and item.done_at is None:
                    self._set_current_locked(item, now)
                elif current is False and item.id == self._current_id:
                    self._set_current_locked(None, now)
                self._save_locked(now)
        return item is not None

    def delete(self, item_id: str, now: float) -> bool:
        with self._lock:
            item = self._find(item_id)
            if item is not None:
                if item.id == self._current_id:
                    self._set_current_locked(None, now)
                self._items.remove(item)
                self._save_locked(now)
        return item is not None

    def track(self, counting: bool, now: float) -> None:
        """Called after every focus check. counting is "working, during a block".

        Like the tracker's totals, the time since the last check goes to what was true at
        that check, capped at MAX_STEP_S so a stall or a clock jump doesn't add hours.
        """
        with self._lock:
            self._roll_day_locked(now)
            current = self._find(self._current_id)
            if self._counting_since is not None and current is not None:
                current.seconds += min(max(0.0, now - self._counting_since), MAX_STEP_S)
                self._unsaved = True
            self._counting_since = now if counting and current is not None else None
            if self._unsaved and now - self._last_saved_at >= SAVE_EVERY_S:
                self._save_locked(now)

    def snapshot(self, now: float) -> dict:
        with self._lock:
            self._roll_day_locked(now)
            done = sorted((item for item in self._items if item.done_at is not None), key=lambda item: item.done_at)
            listed = {
                "current": self._current_id,
                "open": [describe_item(item) for item in self._items if item.done_at is None],
                "done": [describe_item(item) for item in done],
            }
        return listed

    def save(self, now: float) -> None:
        with self._lock:
            self._save_locked(now)

    # ----- inside the lock -----

    def _find(self, item_id: str | None) -> TodoItem | None:
        found = next((item for item in self._items if item.id == item_id), None)
        return found

    def _set_done_locked(self, item: TodoItem, done: bool, now: float) -> None:
        item.done_at = round(now, 3) if done else None
        self._write("done" if done else "undone", item, now)
        if done and item.id == self._current_id:
            self._set_current_locked(None, now)

    def _set_current_locked(self, item: TodoItem | None, now: float) -> None:
        next_id = None if item is None else item.id
        if next_id != self._current_id:
            self._current_id = next_id
            self._counting_since = None
            self._write("current", item, now)

    def _roll_day_locked(self, now: float) -> None:
        today = format_day(now)
        kept = [item for item in self._items if item.done_at is None or format_day(item.done_at) == today]
        if len(kept) != len(self._items):
            self._items = kept
            self._save_locked(now)

    def _write(self, action: str, item: TodoItem | None, now: float) -> None:
        if self._log is not None:
            event = {"ts": round(now, 3), "day": format_day(now), "event": "todo", "action": action, "id": None, "text": None, "seconds": None}
            if item is not None:
                event.update(id=item.id, text=item.text, seconds=round(item.seconds))
            self._log.write(event)

    def _save_locked(self, now: float) -> None:
        data = {"current": self._current_id, "items": [{**asdict(item), "seconds": round(item.seconds, 1)} for item in self._items]}
        temporary = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=1)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            self._unsaved = False
            self._last_saved_at = now
        except OSError:
            logger.exception("to-do list save failed: %s", self._path)

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._items = [TodoItem(**item) for item in data["items"]]
            current = self._find(data.get("current"))
            self._current_id = current.id if current is not None and current.done_at is None else None
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError):
            # Saving an empty list over it would lose everything, so move it aside for a look.
            broken = self._path.with_name(self._path.name + ".broken")
            os.replace(self._path, broken)
            logger.exception("to-do list unreadable, moved to %s and starting empty", broken)
            self._items = []
            self._current_id = None
