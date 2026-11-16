import os
from pathlib import Path


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
