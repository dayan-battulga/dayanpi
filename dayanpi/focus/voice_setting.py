"""Each desk's Settings → Voice and bedtime: its bedtime and where its peace sign speaks.

Kept in the desk's folder as voice.json, {"bedtime": "HH:MM", "output": "pi"|"computer"}, saved whole on every
change. Either one can be missing, which means not picked: app.find_bedtime and app.find_voice_output give the
defaults (00:00; the Pi's speaker for me, this computer for everyone else, since only I can have the speaker).
A file that can't be read means nothing was picked.
"""

from pathlib import Path

from dayanpi.focus.coach import format_bedtime, parse_bedtime
from dayanpi.utils.files import JsonSetting

VOICE_FILE = "voice.json"
OUTPUTS = ("pi", "computer")


class VoiceSetting(JsonSetting):
    def __init__(self, path: Path) -> None:
        super().__init__(path, {"bedtime": None, "output": None})

    def accepts(self, key: str, value: object) -> bool:
        accepted = isinstance(value, str) and parse_bedtime(value) is not None if key == "bedtime" else value in OUTPUTS
        return accepted

    @property
    def bedtime(self) -> int | None:
        """Minutes after midnight."""
        saved = self.read()["bedtime"]
        return None if saved is None else parse_bedtime(saved)

    @property
    def output(self) -> str | None:
        return self.read()["output"]

    def set(self, bedtime: int | None = None, output: str | None = None) -> None:
        """Changes what's given; None leaves it as it is."""
        changes = {"bedtime": None if bedtime is None else format_bedtime(bedtime), "output": output}
        self.update({key: value for key, value in changes.items() if value is not None})
