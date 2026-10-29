"""Focus tracker step 1: what can the camera actually see at your desk?

The dayanpi service owns the camera, so stop it first:
    sudo systemctl stop dayanpi
    .venv/bin/python scripts/focus_check.py
    sudo systemctl start dayanpi

It walks you through three phases (working, on your phone, away), prints what
the detector sees about once a second, saves one marked-up snapshot per phase
into focus_check/ plus a clean frame every 2 seconds into focus_check/frames/,
and ends with a summary (also saved to focus_check/summary.txt).
"""

import argparse
import logging
import statistics
import sys
import time
from dataclasses import dataclass

import cv2
import numpy as np

from dayanpi.hardware.camera import CameraStream, create_stream
from dayanpi.paths import FOCUS_CHECK_DIR
from dayanpi.vision.detector import FACE_MODEL_PATH, OBJECT_MODEL_PATH, DeskScanner, Detection, FrameReading, decode_jpeg, find_best_confidence

OUTPUT_DIR = FOCUS_CHECK_DIR
FRAMES_FOLDER = "frames"
FRAME_SAVE_INTERVAL_S = 2.0
PHASE_SECONDS = 20
GET_READY_SECONDS = 5
SCAN_INTERVAL_S = 1.0
FIRST_FRAME_TIMEOUT_S = 5.0
FIRST_FRAME_POLL_S = 0.1

# Only used for the summary percentages; step 2 picks the real thresholds.
PERSON_SEEN = 0.5
PHONE_SEEN = 0.3

PERSON_COLOR = (80, 200, 80)
PHONE_COLOR = (0, 140, 255)
FACE_COLOR = (255, 200, 0)
TEXT_COLOR = (255, 255, 255)
FONT = cv2.FONT_HERSHEY_SIMPLEX


@dataclass
class Phase:
    name: str
    instruction: str


@dataclass
class PhaseSummary:
    name: str
    frames: int
    person_share: float
    phone_share: float
    face_share: float
    best_phone: float
    median_turn: float | None
    median_tilt: float | None
    average_ms: float


PHASES = [
    Phase("working", "Sit at your desk and work like normal."),
    Phase("phone", "Pick up your phone and use it like you normally would."),
    Phase("away", "Get up and walk out of view."),
]


def format_optional(value: float | None, pattern: str) -> str:
    text = "-" if value is None else format(value, pattern)
    return text


def describe_reading(reading: FrameReading) -> str:
    person = format_optional(find_best_confidence(reading.people) or None, ".2f")
    if len(reading.people) > 1:
        person += f" (x{len(reading.people)})"
    phone = format_optional(find_best_confidence(reading.phones) or None, ".2f")

    face_text = "no face"
    if reading.faces:
        face = max(reading.faces, key=lambda found: found.confidence)
        face_text = f"face turn {face.turn:+.2f} tilt {face.tilt:.2f}"

    snack_text = ""
    snacks = reading.food + reading.drinks
    if snacks:
        best_snack = max(snacks, key=lambda found: found.confidence)
        snack_text = f" | {best_snack.label} {best_snack.confidence:.2f}"

    line = f"person {person:<9} | phone {phone:<4} | {face_text:<25} | {reading.elapsed_ms:4.0f} ms{snack_text}"
    return line


def summarize_phase(name: str, readings: list[FrameReading]) -> PhaseSummary:
    frames = len(readings)
    share_base = max(frames, 1)
    best_faces = [max(reading.faces, key=lambda found: found.confidence) for reading in readings if reading.faces]

    summary = PhaseSummary(
        name=name,
        frames=frames,
        person_share=sum(find_best_confidence(r.people) >= PERSON_SEEN for r in readings) / share_base,
        phone_share=sum(find_best_confidence(r.phones) >= PHONE_SEEN for r in readings) / share_base,
        face_share=len(best_faces) / share_base,
        best_phone=max((find_best_confidence(r.phones) for r in readings), default=0.0),
        median_turn=statistics.median(face.turn for face in best_faces) if best_faces else None,
        median_tilt=statistics.median(face.tilt for face in best_faces) if best_faces else None,
        average_ms=statistics.fmean(r.elapsed_ms for r in readings) if readings else 0.0,
    )
    return summary


def format_report(summaries: list[PhaseSummary]) -> str:
    lines = [
        "",
        "Summary (send this back to Claude):",
        f"person seen = confidence >= {PERSON_SEEN}, phone seen = confidence >= {PHONE_SEEN}",
        "phase    frames  person  phone  face  best phone  turn   tilt   scan",
    ]
    for summary in summaries:
        lines.append(
            f"{summary.name:<8} {summary.frames:>6}  {summary.person_share:>6.0%}  "
            f"{summary.phone_share:>5.0%}  {summary.face_share:>4.0%}  {summary.best_phone:>10.2f}  "
            f"{format_optional(summary.median_turn, '+.2f'):>5}  {format_optional(summary.median_tilt, '.2f'):>5}  "
            f"{summary.average_ms:>4.0f} ms"
        )
    report = "\n".join(lines)
    return report


def draw_box(image: np.ndarray, detection: Detection, color: tuple[int, int, int]) -> None:
    box = detection.box
    top_left = (int(box.x1), int(box.y1))
    cv2.rectangle(image, top_left, (int(box.x2), int(box.y2)), color, 2)
    cv2.putText(
        image,
        f"{detection.label} {detection.confidence:.2f}",
        (top_left[0] + 4, max(top_left[1] - 6, 14)),
        FONT,
        0.5,
        color,
        2,
    )


def draw_reading(image: np.ndarray, reading: FrameReading, caption: str) -> np.ndarray:
    marked = image.copy()
    for person in reading.people:
        draw_box(marked, person, PERSON_COLOR)
    for phone in reading.phones:
        draw_box(marked, phone, PHONE_COLOR)
    for face in reading.faces:
        box = face.box
        cv2.rectangle(marked, (int(box.x1), int(box.y1)), (int(box.x2), int(box.y2)), FACE_COLOR, 2)
        for point in face.landmarks:
            cv2.circle(marked, (int(point.x), int(point.y)), 3, FACE_COLOR, -1)

    cv2.rectangle(marked, (0, 0), (marked.shape[1], 24), (0, 0, 0), -1)
    cv2.putText(marked, caption, (6, 17), FONT, 0.5, TEXT_COLOR, 1)
    return marked


def wait_for_first_frame(stream: CameraStream) -> bytes | None:
    deadline = time.monotonic() + FIRST_FRAME_TIMEOUT_S
    jpeg = stream.latest_frame()
    while jpeg is None and time.monotonic() < deadline:
        time.sleep(FIRST_FRAME_POLL_S)
        jpeg = stream.latest_frame()
    return jpeg


def count_down(phase: Phase, seconds: int) -> None:
    print(f"\nNext: {phase.name.upper()}. {phase.instruction}")
    for remaining in range(seconds, 0, -1):
        print(f"  starting in {remaining}...", end="\r", flush=True)
        time.sleep(1)
    print(" " * 30, end="\r")


def clear_saved_frames() -> None:
    frames_dir = OUTPUT_DIR / FRAMES_FOLDER
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old_frame in frames_dir.glob("*.jpg"):
        old_frame.unlink()


def run_phase(stream: CameraStream, scanner: DeskScanner, phase: Phase, seconds: int) -> PhaseSummary:
    readings = []
    snapshot_saved = False
    frames_dir = OUTPUT_DIR / FRAMES_FOLDER
    frames_saved = 0
    next_frame_save = 0.0
    started = time.monotonic()
    elapsed = 0.0

    while elapsed < seconds:
        tick = time.monotonic()
        jpeg = stream.latest_frame()
        image = None if jpeg is None else decode_jpeg(jpeg)
        if image is not None:
            reading = scanner.scan(image)
            readings.append(reading)
            print(f"[{phase.name:<7} {elapsed:3.0f}s] {describe_reading(reading)}")
            if elapsed >= next_frame_save:
                # The camera's own JPEG bytes, unmarked: drawn boxes fool the model when re-testing.
                (frames_dir / f"{phase.name}_{frames_saved:02d}.jpg").write_bytes(jpeg)
                frames_saved += 1
                next_frame_save = elapsed + FRAME_SAVE_INTERVAL_S
            if not snapshot_saved and elapsed >= seconds / 2:
                caption = f"{phase.name}: {describe_reading(reading)}"
                cv2.imwrite(str(OUTPUT_DIR / f"{phase.name}.jpg"), draw_reading(image, reading, caption))
                snapshot_saved = True
        time.sleep(max(0.0, SCAN_INTERVAL_S - (time.monotonic() - tick)))
        elapsed = time.monotonic() - started

    summary = summarize_phase(phase.name, readings)
    return summary


def run_check(seconds: int) -> int:
    print("Loading models...")
    scanner = DeskScanner()
    stream = create_stream()
    stream.start()
    exit_code = 0

    try:
        jpeg = wait_for_first_frame(stream)
        image = None if jpeg is None else decode_jpeg(jpeg)
        if image is None:
            print(
                "No camera frames. If the dayanpi service is running, it has the camera:\n"
                "  sudo systemctl stop dayanpi"
            )
            exit_code = 1
        else:
            warmup = scanner.scan(image)
            print(f"Camera frame is {image.shape[1]}x{image.shape[0]}. First scan took {warmup.elapsed_ms:.0f} ms.")
            summaries = []
            for phase in PHASES:
                count_down(phase, GET_READY_SECONDS)
                summaries.append(run_phase(stream, scanner, phase, seconds))
            report = format_report(summaries)
            print(report)
            (OUTPUT_DIR / "summary.txt").write_text(report + "\n")
            print(f"\nSnapshots and summary are in {OUTPUT_DIR}/, clean frames in {OUTPUT_DIR / FRAMES_FOLDER}/")
    finally:
        stream.stop()

    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Check what the focus detector sees at your desk.")
    parser.add_argument("--seconds", type=int, default=PHASE_SECONDS, help="length of each phase (default 20)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    OUTPUT_DIR.mkdir(exist_ok=True)
    clear_saved_frames()

    missing = [path.name for path in (OBJECT_MODEL_PATH, FACE_MODEL_PATH) if not path.exists()]
    exit_code = 1
    if missing:
        print(f"Missing model files in models/: {', '.join(missing)}. See 'Where the models come from' in docs/MANUAL.md.")
    else:
        exit_code = run_check(args.seconds)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
