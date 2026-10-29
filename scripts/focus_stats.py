"""Prints the focus report (dayanpi.focus.stats) from a plain checkout, no install needed.

    .venv/bin/python scripts/focus_stats.py            # today
    .venv/bin/python scripts/focus_stats.py --days 7   # the last week
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dayanpi.focus.stats import main  # noqa: E402  (needs the repo root on sys.path first)

if __name__ == "__main__":
    sys.exit(main())
