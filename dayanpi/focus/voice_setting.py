"""Each desk's Settings → Voice and bedtime: its bedtime and where its peace sign speaks.

Kept in the desk's folder as voice.json, {"bedtime": "HH:MM", "output": "pi"|"computer"}, saved whole on every
change. Either one can be missing, which means not picked: app.find_bedtime and app.find_voice_output give the
defaults (my bedtime from DAYANPI_BEDTIME, everyone else's 00:00; the Pi's speaker for me, this computer for
everyone else, since only I can have the speaker). A file that can't be read means nothing was picked.
"""

import json
import logging
import threading
from pathlib import Path

from dayanpi.focus.coach import format_bedtime, parse_bedtime
from dayanpi.utils.files import write_atomically

VOICE_FILE = "voice.json"
OUTPUTS = ("pi", "computer")

logger = logging.getLogger(__name__)


class VoiceSetting:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self.bedtime: int | None = None  # minutes after midnight
        self.output: str | None = None
        self._load()

    def set(self, bedtime: int | None = None, output: str | None = None) -> None:
        """Changes what's given and saves both. A failed save is logged; the change holds until the next restart."""
        with self._lock:
            self.bedtime = self.bedtime if bedtime is None else bedtime
            self.output = self.output if output is None else output
            saved = {"bedtime": None if self.bedtime is None else format_bedtime(self.bedtime), "output": self.output}
            try:
                write_atomically(self._path, json.dumps(saved))
            except OSError:
                logger.exception("voice setting save failed: %s", self._path)

    def _load(self) -> None:
        try:
            saved = json.loads(self._path.read_text(encoding="utf-8"))
            bedtime = saved.get("bedtime")
            self.bedtime = parse_bedtime(bedtime) if isinstance(bedtime, str) else None
            self.output = saved.get("output") if saved.get("output") in OUTPUTS else None
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            logger.warning("couldn't read %s, so the voice settings are the defaults", self._path)
