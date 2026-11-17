"""Where a desk's focus checks come from: the Pi's cameras or a browser's (the /track page).

Each desk keeps its pick in its folder's camera_source.json (focus/desks.py), as {"source": "pi"|"browser"}, saved
whole on every change. Only the owner's desk can have the Pi's cameras (app.find_camera_source), so a member's pick
is always the browser. No file, or one that can't be read, means nothing was picked.
"""

import json
import logging
import threading
from pathlib import Path

from dayanpi.utils.files import write_atomically

CAMERA_SOURCE_FILE = "camera_source.json"
SOURCES = ("pi", "browser")

logger = logging.getLogger(__name__)


class CameraSourceSetting:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self.source: str | None = self._load()

    def set(self, source: str) -> bool:
        """Returns whether it changed. A failed save is logged; the pick still holds until the next restart."""
        with self._lock:
            changed = source != self.source
            if changed:
                self.source = source
                try:
                    write_atomically(self._path, json.dumps({"source": source}))
                except OSError:
                    logger.exception("camera source save failed: %s", self._path)
        return changed

    def _load(self) -> str | None:
        source = None
        try:
            saved = json.loads(self._path.read_text(encoding="utf-8")).get("source")
            source = saved if saved in SOURCES else None
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            logger.warning("couldn't read %s, so the camera source is the default", self._path)
        return source
