"""Where things live on disk, relative to this package, so no module has to count parent dirs."""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent

STATIC_DIR = PACKAGE_DIR / "static"
MODELS_DIR = REPO_ROOT / "models"
DEFAULT_DATA_DIR = REPO_ROOT / "data"
FOCUS_CHECK_DIR = REPO_ROOT / "focus_check"
