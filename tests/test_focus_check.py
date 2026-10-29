import sys

import cv2
import numpy as np
import pytest

import focus_check
from detector import Box, Detection, FaceReading, FrameReading, Point

BOX = Box(x1=10, y1=10, x2=50, y2=50)


def make_reading(person: float = 0.0, phone: float = 0.0, tilt: float | None = None) -> FrameReading:
    people = [Detection("person", person, BOX)] if person else []
    phones = [Detection("phone", phone, BOX)] if phone else []
    faces = [] if tilt is None else [FaceReading(0.9, BOX, [Point(20, 20)] * 5, turn=0.0, tilt=tilt)]
    return FrameReading(people=people, phones=phones, faces=faces, elapsed_ms=200.0)


def test_summary_counts_frames_over_the_seen_thresholds():
    readings = [
        make_reading(person=0.9, phone=0.6, tilt=0.7),
        make_reading(person=0.9, phone=0.2, tilt=0.5),
        make_reading(person=0.3),
        make_reading(),
    ]
    summary = focus_check.summarize_phase("phone", readings)
    assert summary.frames == 4
    assert summary.person_share == pytest.approx(0.5)
    assert summary.phone_share == pytest.approx(0.25)
    assert summary.face_share == pytest.approx(0.5)
    assert summary.best_phone == pytest.approx(0.6)
    assert summary.median_tilt == pytest.approx(0.6)
    assert summary.average_ms == pytest.approx(200.0)


def test_summary_of_an_empty_phase_does_not_crash():
    summary = focus_check.summarize_phase("away", [])
    assert summary.frames == 0
    assert summary.median_turn is None
    assert "away" in focus_check.format_report([summary])


def test_reading_line_shows_best_hits():
    line = focus_check.describe_reading(make_reading(person=0.91, phone=0.42, tilt=0.47))
    assert "person 0.91" in line
    assert "phone 0.42" in line
    assert "tilt 0.47" in line


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

    summary = focus_check.run_phase(FakeStream(), FakeScanner(), focus_check.PHASES[1], 1.0)  # a 0.5 s window to save the snapshot, so a busy machine can't miss it

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
