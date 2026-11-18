"""The dashboard's switch for the Mac helper: whether its app and site reports count.

Each desk keeps its own, in its folder's mac_tracking.json (focus/desks.py), as {"enabled": true|false},
saved whole on every change, so a restart keeps the last pick. No file means on; a file
that can't be read also means on, with one warning.
"""

from pathlib import Path

from dayanpi.utils.files import JsonSetting

MAC_TRACKING_FILE = "mac_tracking.json"


class MacTrackingSetting(JsonSetting):
    def __init__(self, path: Path) -> None:
        super().__init__(path, {"enabled": True})

    def accepts(self, key: str, value: object) -> bool:
        return isinstance(value, bool)

    @property
    def enabled(self) -> bool:
        return self.read()["enabled"]

    def set(self, enabled: bool) -> bool:
        """Returns whether it changed."""
        return self.update({"enabled": enabled})
