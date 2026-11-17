"""The dashboard's switch for the Mac helper: whether its app and site reports count.

Each desk keeps its own, in its folder's mac_tracking.json (focus/desks.py), as {"enabled": true|false},
saved whole on every change, so a restart keeps the last pick. No file means on; a file
that can't be read also means on, with one warning.
"""

import json
import logging
import threading
from pathlib import Path

from dayanpi.utils.files import write_atomically

MAC_TRACKING_FILE = "mac_tracking.json"

logger = logging.getLogger(__name__)


class MacTrackingSetting:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self.enabled = self._load()

    def set(self, enabled: bool) -> bool:
        """Returns whether it changed. A failed save is logged; the switch still flips until the next restart."""
        with self._lock:
            changed = enabled != self.enabled
            if changed:
                self.enabled = enabled
                try:
                    write_atomically(self._path, json.dumps({"enabled": enabled}))
                except OSError:
                    logger.exception("Mac tracking setting save failed: %s", self._path)
        return changed

    def _load(self) -> bool:
        enabled = True
        try:
            saved = json.loads(self._path.read_text(encoding="utf-8")).get("enabled")
            enabled = saved if isinstance(saved, bool) else True
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            logger.warning("couldn't read %s, so Mac tracking is on", self._path)
        return enabled
