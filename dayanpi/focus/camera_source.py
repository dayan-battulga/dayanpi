"""Where a desk's focus checks come from, and its seat's picture: the Pi's cameras or a browser's.

Each desk keeps its picks in its folder's camera_source.json (focus/desks.py), as {"source", "picture"}, each
"pi"|"browser"|null, saved whole on every change. Only the owner's desk can have the Pi's cameras
(app.find_camera_source, app.find_picture_source), so a member's picks are always the browser. No file, or one that
can't be read, means nothing was picked, and an unpicked picture follows the source.
"""

from pathlib import Path

from dayanpi.utils.files import JsonSetting

CAMERA_SOURCE_FILE = "camera_source.json"
SOURCES = ("pi", "browser")


class CameraSourceSetting(JsonSetting):
    def __init__(self, path: Path) -> None:
        super().__init__(path, {"source": None, "picture": None})

    def accepts(self, key: str, value: object) -> bool:
        return value in SOURCES

    @property
    def source(self) -> str | None:
        return self.read()["source"]

    @property
    def picture(self) -> str | None:
        return self.read()["picture"]

    def set(self, source: str) -> bool:
        """Returns whether it changed."""
        return self.update({"source": source})
