"""Replays the clean frames from a focus_check run through the real detector and the state machine.

Skipped unless focus_check/frames/ exists (it's gitignored; focus_check.py writes it on the Pi).
"""

from pathlib import Path

import pytest

import detector
from focus import FocusTracker

FRAMES_DIR = Path(__file__).resolve().parent.parent / "focus_check" / "frames"
PHASES = ("working", "phone", "away")


def phase_frames(phase: str) -> list[Path]:
    frames = sorted(FRAMES_DIR.glob(f"{phase}_*.jpg"))
    return frames


@pytest.mark.skipif(
    not (FRAMES_DIR.exists() and detector.OBJECT_MODEL_PATH.exists() and detector.FACE_MODEL_PATH.exists()),
    reason="needs focus_check/frames/ and the models",
)
def test_real_frames_walk_through_the_three_states():
    import cv2

    scanner = detector.DeskScanner()
    tracker = FocusTracker(started_at=0.0)
    now = 0.0
    seen = {}
    for phase in PHASES:
        frames = phase_frames(phase)
        assert frames, f"no {phase} frames"
        # Each saved frame stands in for a few seconds of that phase.
        for path in frames:
            reading = scanner.scan(cv2.imread(str(path)))
            for _ in range(3):
                now += 1.0
                state = tracker.update(reading, now).state
        seen[phase] = state

    assert seen["working"] == "working"
    assert seen["phone"] == "phone"
    assert seen["away"] == "away"
    today = tracker.status(now)["today"]
    assert today["pickups"] == 1
