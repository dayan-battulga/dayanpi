"""Focus tracker step 1: what can the camera actually see at your desk?

The dayanpi service owns the camera, so stop it first:
    sudo systemctl stop dayanpi
    .venv/bin/python -m dayanpi.focus.check
    sudo systemctl start dayanpi

It walks you through four phases (working, working with your hand on your mouse,
on your phone, away), prints what the detector sees about once a second, saves one
marked-up snapshot per phase into focus_check/ plus a clean frame every 2 seconds
into focus_check/frames/, and ends with a summary (also saved to focus_check/summary.txt):
each phase's phone scores before and after the mouse veto, and the PHONE_MIN that keeps
the mouse phase under it while most phone checks stay over it, if there is one.
"""

import argparse
import logging
import math
import statistics
import sys
import time
from dataclasses import dataclass

import cv2
import numpy as np

from dayanpi.hardware.camera import CameraStream, create_stream
from dayanpi.paths import FOCUS_CHECK_DIR
from dayanpi.focus.tracker import PHONE_ENTER_HITS, PHONE_MIN, PHONE_WINDOW
from dayanpi.vision.detector import (
    FACE_MODEL_PATH,
    OBJECT_MODEL_PATH,
    DeskScanner,
    Detection,
    FrameReading,
    decode_jpeg,
    drop_mouse_phones,
    find_best_confidence,
)

OUTPUT_DIR = FOCUS_CHECK_DIR
FRAMES_FOLDER = "frames"
FRAME_SAVE_INTERVAL_S = 2.0
PHASE_SECONDS = 20
GET_READY_SECONDS = 5
SCAN_INTERVAL_S = 1.0
FIRST_FRAME_TIMEOUT_S = 5.0

# Only used for the summary percentages; step 2 picks the real thresholds.
PERSON_SEEN = 0.5
# The suggested PHONE_MIN: the lowest 0.05 step over everything the working and mouse phases scored, never under the
# old 0.5, and only if at least 3 of 5 phone checks reach it, since that's what the tracker needs to say "phone".
SUGGEST_STEP_HUNDREDTHS = 5
SUGGEST_FLOOR = 0.5
SUGGEST_PHONE_SHARE = PHONE_ENTER_HITS / PHONE_WINDOW
NOT_A_PHONE_PHASES = ("working", "mouse")

PERSON_COLOR = (80, 200, 80)
PHONE_COLOR = (0, 140, 255)
MOUSE_COLOR = (200, 80, 200)
FACE_COLOR = (255, 200, 0)
TEXT_COLOR = (255, 255, 255)
FONT = cv2.FONT_HERSHEY_SIMPLEX


@dataclass
class Phase:
    name: str
    instruction: str


@dataclass
class ScoreSpread:
    median: float
    p90: float
    highest: float


@dataclass
class PhaseSummary:
    name: str
    frames: int
    person_share: float
    face_share: float
    phone_before: ScoreSpread  # each check's best phone, as the model scored it
    phone_after: ScoreSpread  # the same after drop_mouse_phones, which is what the tracker gets
    phone_scores: list[float]  # each check's best phone after the veto, for the suggestion
    median_turn: float | None
    median_tilt: float | None
    average_ms: float


PHASES = [
    Phase("working", "Sit at your desk and work like normal."),
    Phase("mouse", "Keep working, with your hand on your mouse: move it, scroll, click."),
    Phase("phone", "Pick up your phone and use it like you normally would."),
    Phase("away", "Get up and walk out of view."),
]


def format_optional(value: float | None, pattern: str) -> str:
    text = "-" if value is None else format(value, pattern)
    return text


def score_phone(reading: FrameReading) -> float:
    """The check's best phone after the mouse veto, as the live tracker would get it (before the hand check)."""
    score = find_best_confidence(drop_mouse_phones(reading.phones, reading.mice))
    return score


def spread_scores(scores: list[float]) -> ScoreSpread:
    """Median, 90th percentile (nearest rank) and highest; all 0 with no checks."""
    ordered = sorted(scores)
    spread = ScoreSpread(
        median=statistics.median(ordered) if ordered else 0.0,
        p90=ordered[math.ceil(0.9 * len(ordered)) - 1] if ordered else 0.0,
        highest=ordered[-1] if ordered else 0.0,
    )
    return spread


def find_highest_fake(summaries: list[PhaseSummary]) -> float:
    """The highest phone score (after the veto) while there was no phone: the working and mouse phases."""
    highest = max((summary.phone_after.highest for summary in summaries if summary.name in NOT_A_PHONE_PHASES), default=0.0)
    return highest


def find_phone_scores(summaries: list[PhaseSummary]) -> list[float]:
    scores = next((summary.phone_scores for summary in summaries if summary.name == "phone"), [])
    return scores


def suggest_phone_min(summaries: list[PhaseSummary]) -> float | None:
    """The lowest 0.05 step over every working and mouse check (after the veto), at least SUGGEST_FLOOR, or None when
    fewer than SUGGEST_PHONE_SHARE of the phone checks reach it: then no cutoff separates a mouse from a phone."""
    steps = math.floor(round(find_highest_fake(summaries) * 100, 6) / SUGGEST_STEP_HUNDREDTHS) + 1
    cutoff = max(SUGGEST_FLOOR, steps * SUGGEST_STEP_HUNDREDTHS / 100)
    phone_scores = find_phone_scores(summaries)
    reaching = sum(score >= cutoff for score in phone_scores) / max(len(phone_scores), 1)
    suggestion = cutoff if phone_scores and reaching >= SUGGEST_PHONE_SHARE else None
    return suggestion


def describe_reading(reading: FrameReading) -> str:
    person = format_optional(find_best_confidence(reading.people) or None, ".2f")
    if len(reading.people) > 1:
        person += f" (x{len(reading.people)})"
    before = format_optional(find_best_confidence(reading.phones) or None, ".2f")
    after = format_optional(score_phone(reading) or None, ".2f")
    mouse = format_optional(find_best_confidence(reading.mice) or None, ".2f")
    phone = before if before == after else f"{before}>{after}"

    face_text = "no face"
    if reading.faces:
        face = max(reading.faces, key=lambda found: found.confidence)
        face_text = f"face turn {face.turn:+.2f} tilt {face.tilt:.2f}"

    line = f"person {person:<9} | phone {phone:<9} | mouse {mouse:<4} | {face_text:<25} | {reading.elapsed_ms:4.0f} ms"
    return line


def summarize_phase(name: str, readings: list[FrameReading]) -> PhaseSummary:
    frames = len(readings)
    share_base = max(frames, 1)
    best_faces = [max(reading.faces, key=lambda found: found.confidence) for reading in readings if reading.faces]

    phone_scores = [score_phone(r) for r in readings]
    summary = PhaseSummary(
        name=name,
        frames=frames,
        person_share=sum(find_best_confidence(r.people) >= PERSON_SEEN for r in readings) / share_base,
        face_share=len(best_faces) / share_base,
        phone_before=spread_scores([find_best_confidence(r.phones) for r in readings]),
        phone_after=spread_scores(phone_scores),
        phone_scores=phone_scores,
        median_turn=statistics.median(face.turn for face in best_faces) if best_faces else None,
        median_tilt=statistics.median(face.tilt for face in best_faces) if best_faces else None,
        average_ms=statistics.fmean(r.elapsed_ms for r in readings) if readings else 0.0,
    )
    return summary


def format_spread(spread: ScoreSpread) -> str:
    text = f"{spread.median:.2f} {spread.p90:.2f} {spread.highest:.2f}"
    return text


def describe_suggestion(summaries: list[PhaseSummary]) -> str:
    suggestion = suggest_phone_min(summaries)
    text = (
        f"Suggested PHONE_MIN: {suggestion:.2f} (now {PHONE_MIN}): over every working and mouse check, and at least "
        f"{SUGGEST_PHONE_SHARE:.0%} of phone checks reach it."
        if suggestion is not None
        else f"No PHONE_MIN separates them: working and the mouse went up to {find_highest_fake(summaries):.2f} after the "
        f"veto, and fewer than {SUGGEST_PHONE_SHARE:.0%} of phone checks scored above that "
        f"(phone median {spread_scores(find_phone_scores(summaries)).median:.2f})."
    )
    return text


def format_report(summaries: list[PhaseSummary]) -> str:
    lines = [
        "",
        "Summary (send this back to Claude):",
        f"person seen = confidence >= {PERSON_SEEN}; phone = each check's best phone, as median p90 highest,",
        "before and after the mouse veto (after is what the tracker gets)",
        "phase    frames  person  face  phone before      phone after       turn   tilt   scan",
    ]
    for summary in summaries:
        lines.append(
            f"{summary.name:<8} {summary.frames:>6}  {summary.person_share:>6.0%}  {summary.face_share:>4.0%}  "
            f"{format_spread(summary.phone_before):<16}  {format_spread(summary.phone_after):<16}  "
            f"{format_optional(summary.median_turn, '+.2f'):>5}  {format_optional(summary.median_tilt, '.2f'):>5}  "
            f"{summary.average_ms:>4.0f} ms"
        )
    lines.append(describe_suggestion(summaries))
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
    for mouse in reading.mice:
        draw_box(marked, mouse, MOUSE_COLOR)
    for face in reading.faces:
        box = face.box
        cv2.rectangle(marked, (int(box.x1), int(box.y1)), (int(box.x2), int(box.y2)), FACE_COLOR, 2)
        for point in face.landmarks:
            cv2.circle(marked, (int(point.x), int(point.y)), 3, FACE_COLOR, -1)

    cv2.rectangle(marked, (0, 0), (marked.shape[1], 24), (0, 0, 0), -1)
    cv2.putText(marked, caption, (6, 17), FONT, 0.5, TEXT_COLOR, 1)
    return marked


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
        first = stream.frame_after(-1, timeout=FIRST_FRAME_TIMEOUT_S)
        image = None if first is None else decode_jpeg(first[0])
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
        print(f"Missing model files in models/: {', '.join(missing)}. See 'Where the models come from' in docs/focus-tracker.md.")
    else:
        exit_code = run_check(args.seconds)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
