import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


def write_atomically(path: Path, text: str) -> None:
    """Writes a temp file next to path and swaps it in, so a power cut leaves the old file or the new one, never half of one.

    Raises OSError like any other write; the caller decides what a failed save means.
    """
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class JsonSetting:
    """A desk's small settings file, {key: value}, saved whole when something changes. Thread-safe.

    No file means the defaults. A file that can't be read means the defaults too, with one warning, and a saved
    value accepts() turns down means that key's default. A failed save is logged; the change holds until a restart.
    Subclasses give the defaults and accepts().
    """

    def __init__(self, path: Path, defaults: dict) -> None:
        self._path = path
        self._defaults = defaults
        self._lock = threading.Lock()
        self._values = self._load()

    def accepts(self, key: str, value: object) -> bool:
        raise NotImplementedError

    def read(self) -> dict:
        with self._lock:
            values = dict(self._values)
        return values

    def update(self, changes: dict) -> bool:
        """Changes the known keys given. Returns whether anything changed; only then is the file saved."""
        with self._lock:
            known = {key: value for key, value in changes.items() if key in self._defaults}
            changed = any(self._values[key] != value for key, value in known.items())
            if changed:
                self._values.update(known)
                try:
                    write_atomically(self._path, json.dumps(self._values))
                except OSError:
                    logger.exception("couldn't save %s", self._path)
        return changed

    def _load(self) -> dict:
        values = dict(self._defaults)
        try:
            saved = json.loads(self._path.read_text(encoding="utf-8"))
            values.update({key: value for key, value in saved.items() if key in self._defaults and self.accepts(key, value)})
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            logger.warning("couldn't read %s, so it's the defaults", self._path)
        return values
