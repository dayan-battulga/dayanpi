"""Runs the guided detector check (dayanpi.focus.check) from a plain checkout, no install needed.

    sudo systemctl stop dayanpi
    .venv/bin/python scripts/focus_check.py
    sudo systemctl start dayanpi
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dayanpi.focus.check import main  # noqa: E402  (needs the repo root on sys.path first)

if __name__ == "__main__":
    sys.exit(main())
