import sys

import cv2
import numpy as np
import pytest

from dayanpi.focus import check as focus_check
from dayanpi.vision.detector import Box, Detection, FaceReading, FrameReading, Point

BOX = Box(x1=10, y1=10, x2=50, y2=50)


def make_reading(person: float = 0.0, phone: float = 0.0, tilt: float | None = None, mouse: float = 0.0) -> FrameReading:
    people = [Detection("person", person, BOX)] if person else []
    phones = [Detection("phone", phone, BOX)] if phone else []
    mice = [Detection("mouse", mouse, BOX)] if mouse else []
    faces = [] if tilt is None else [FaceReading(0.9, BOX, [Point(20, 20)] * 5, turn=0.0, tilt=tilt)]
    return FrameReading(people=people, phones=phones, faces=faces, elapsed_ms=200.0, mice=mice)


def test_summary_counts_frames_and_spreads_the_phone_scores_before_and_after_the_veto():
    readings = [
        make_reading(person=0.9, phone=0.6, tilt=0.7),
        make_reading(person=0.9, phone=0.7, tilt=0.5, mouse=0.8),  # the mouse outscores it: gone after the veto
        make_reading(person=0.3),
        make_reading(),
    ]
    summary = focus_check.summarize_phase("phone", readings)
    assert summary.frames == 4
    assert summary.person_share == pytest.approx(0.5)
    assert summary.face_share == pytest.approx(0.5)
    assert summary.phone_before == focus_check.ScoreSpread(median=0.3, p90=0.7, highest=0.7)
    assert summary.phone_after == focus_check.ScoreSpread(median=0.0, p90=0.6, highest=0.6)
    assert summary.phone_scores == [0.6, 0.0, 0.0, 0.0]
    assert summary.median_tilt == pytest.approx(0.6)
    assert summary.average_ms == pytest.approx(200.0)


def test_the_spread_is_median_nearest_rank_p90_and_highest():
    scores = [index / 10 for index in range(10, 0, -1)]  # 1.0 down to 0.1
    assert focus_check.spread_scores(scores) == focus_check.ScoreSpread(median=pytest.approx(0.55), p90=0.9, highest=1.0)
    assert focus_check.spread_scores([0.4]) == focus_check.ScoreSpread(median=0.4, p90=0.4, highest=0.4)
    assert focus_check.spread_scores([]) == focus_check.ScoreSpread(median=0.0, p90=0.0, highest=0.0)


def summarize(working: list[float], mouse: list[float], phone: list[float]) -> list:
    """Three phases whose checks score these phones (after the veto), plus an empty away."""
    phases = {"working": working, "mouse": mouse, "phone": phone, "away": []}
    summaries = [focus_check.summarize_phase(name, [make_reading(person=0.9, phone=score) for score in scores]) for name, scores in phases.items()]
    return summaries


@pytest.mark.parametrize(
    "mouse, phone, suggestion",
    [
        ([0.3, 0.57, 0.4], [0.7, 0.8, 0.65, 0.5, 0.75], 0.6),  # the next 0.05 step over the mouse's 0.57
        ([0.3, 0.55], [0.7, 0.8, 0.65, 0.5, 0.75], 0.6),  # strictly over: 0.55 itself would count it
        ([0.2, 0.0], [0.7, 0.8, 0.65, 0.5, 0.75], 0.5),  # never under the old 0.5
        ([0.3, 0.62], [0.7, 0.8, 0.66, 0.6, 0.6], 0.65),  # 3 of 5 phone checks reach 0.65: enough
        ([0.3, 0.62], [0.7, 0.8, 0.64, 0.6, 0.6], None),  # only 2 of 5: no cutoff separates them
        ([0.3, 0.62], [], None),  # no phone checks
    ],
)
def test_the_suggested_phone_min_keeps_the_mouse_under_it_and_most_phones_over_it(mouse, phone, suggestion):
    summaries = summarize([0.0, 0.1], mouse, phone)
    assert focus_check.suggest_phone_min(summaries) == suggestion
    report = focus_check.format_report(summaries)
    if suggestion is None:
        assert "No PHONE_MIN separates them: working and the mouse went up to 0.62" in report
        assert "Suggested" not in report
    else:
        assert f"Suggested PHONE_MIN: {suggestion:.2f} (now 0.6)" in report
    assert "mouse" in report and "phone before" in report and "phone after" in report


def test_working_counts_toward_the_fakes_too():
    assert focus_check.suggest_phone_min(summarize([0.71], [0.2], [0.8, 0.8, 0.8])) == pytest.approx(0.75)


def test_summary_of_an_empty_phase_does_not_crash():
    summary = focus_check.summarize_phase("away", [])
    assert summary.frames == 0
    assert summary.median_turn is None
    assert "away" in focus_check.format_report([summary])


def test_reading_line_shows_best_hits():
    line = focus_check.describe_reading(make_reading(person=0.91, phone=0.42, tilt=0.47))
    assert "person 0.91" in line
    assert "phone 0.42 " in line
    assert "mouse -" in line
    assert "tilt 0.47" in line
    vetoed = focus_check.describe_reading(make_reading(person=0.91, phone=0.42, mouse=0.5))
    assert "phone 0.42>-" in vetoed and "mouse 0.50" in vetoed


def test_the_check_has_a_mouse_phase_between_working_and_the_phone():
    assert [phase.name for phase in focus_check.PHASES] == ["working", "mouse", "phone", "away"]


def test_reading_line_for_an_empty_desk():
    line = focus_check.describe_reading(make_reading())
    assert "person -" in line
    assert "no face" in line


def test_main_stops_early_when_a_model_is_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(focus_check, "OBJECT_MODEL_PATH", tmp_path / "missing.onnx")
    monkeypatch.setattr(focus_check, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(sys, "argv", ["focus_check.py"])
    assert focus_check.main() == 1
    assert "missing.onnx" in capsys.readouterr().out


class FakeStream:
    def latest_frame(self) -> bytes:
        return cv2.imencode(".jpg", np.full((480, 640, 3), 90, np.uint8))[1].tobytes()


class FakeScanner:
    def scan(self, image: np.ndarray) -> FrameReading:
        return make_reading(person=0.9, phone=0.4, tilt=0.5)


def test_run_phase_saves_clean_frames_and_one_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(focus_check, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(focus_check, "SCAN_INTERVAL_S", 0.1)
    monkeypatch.setattr(focus_check, "FRAME_SAVE_INTERVAL_S", 0.0)
    focus_check.clear_saved_frames()
    stale = tmp_path / "frames" / "old.jpg"
    stale.write_bytes(b"x")
    focus_check.clear_saved_frames()

    phone_phase = next(phase for phase in focus_check.PHASES if phase.name == "phone")
    summary = focus_check.run_phase(FakeStream(), FakeScanner(), phone_phase, 1.0)  # a 0.5 s window to save the snapshot, so a busy machine can't miss it

    frames = sorted(path.name for path in (tmp_path / "frames").glob("*.jpg"))
    assert not stale.exists()
    assert len(frames) == summary.frames
    assert frames[0] == "phone_00.jpg"
    assert (tmp_path / "frames" / "phone_00.jpg").read_bytes() == FakeStream().latest_frame()
    assert (tmp_path / "phone.jpg").exists()


def test_draw_reading_keeps_the_frame_size():
    frame = np.zeros((480, 640, 3), np.uint8)
    marked = focus_check.draw_reading(frame, make_reading(person=0.9, phone=0.5, tilt=0.5), "caption")
    assert marked.shape == frame.shape
    assert not np.array_equal(marked, frame)
    assert frame.sum() == 0
