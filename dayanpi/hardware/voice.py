"""Says short phrases out loud ("Phone down.", "Break's over.") through a USB speaker.

The trap: dayanpi runs as a systemd *system* service, and a system service can't
reach the desktop's PipeWire/PulseAudio session. So every phrase plays straight
through ALSA's aplay, on DAYANPI_AUDIO_DEVICE when it's set (for example
plughw:CARD=Device,DEV=0), or on ALSA's default device when it isn't.

Settings come from the environment (/etc/dayanpi.env on the Pi):
- DAYANPI_VOICE: "off" (the default, which only logs what it would have said),
  "espeak" (espeak-ng from apt) or "piper" (piper-tts from pip, in the venv)
- DAYANPI_PIPER_MODEL: path to a Piper voice .onnx, with its .onnx.json next to it
- DAYANPI_AUDIO_DEVICE: the ALSA device aplay plays on

If the chosen voice can't run, it logs one error and stays off. The app carries on.
"""

import importlib.metadata
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

VOICE_ENV = "DAYANPI_VOICE"
PIPER_MODEL_ENV = "DAYANPI_PIPER_MODEL"
AUDIO_DEVICE_ENV = "DAYANPI_AUDIO_DEVICE"

OFF = "off"
ESPEAK = "espeak"
PIPER = "piper"
BACKENDS = (OFF, ESPEAK, PIPER)

QUEUE_SIZE = 3
STEP_TIMEOUT_S = 20.0
STOP_JOIN_TIMEOUT_S = 1.0

PLAYER_PROGRAM = "aplay"
ESPEAK_PROGRAM = "espeak-ng"
ESPEAK_VOICE = "en-us"
ESPEAK_WORDS_PER_MINUTE = 165
PIPER_PACKAGE = "piper-tts"
PIPER_DEFAULT_SAMPLE_RATE = 22050
PIPER_SAMPLE_FORMAT = "S16_LE"

logger = logging.getLogger(__name__)


class SpeechError(Exception):
    """A phrase couldn't be spoken: a program wouldn't start, failed, or got stuck and was killed."""


@dataclass
class VoiceSettings:
    backend: str
    piper_model: Path | None
    audio_device: str | None


@dataclass
class SpeechJob:
    """One phrase: the synth program turns text_input into audio, then aplay plays it."""

    synth_name: str
    synth_command: list[str]
    player_command: list[str]
    text_input: bytes


def read_settings(environ: Mapping[str, str] = os.environ) -> VoiceSettings:
    model_text = environ.get(PIPER_MODEL_ENV, "").strip()
    settings = VoiceSettings(
        backend=environ.get(VOICE_ENV, "").strip().lower() or OFF,
        # systemd's EnvironmentFile doesn't expand ~, so a path written with it would never be found.
        piper_model=Path(model_text).expanduser() if model_text else None,
        audio_device=environ.get(AUDIO_DEVICE_ENV, "").strip() or None,
    )
    return settings


def clean_text(text: str) -> str:
    """One line of plain text: control characters dropped, newlines and other whitespace squashed to single spaces."""
    printable = "".join(character for character in text if character.isprintable() or character.isspace())
    cleaned = " ".join(printable.split())
    return cleaned


def encode_text(text: str) -> bytes:
    """Both synths read the phrase from stdin, so it never ends up on a command line."""
    text_input = (text + "\n").encode("utf-8")
    return text_input


def derive_config_path(model: Path) -> Path:
    config_path = model.with_name(model.name + ".json")
    return config_path


def read_sample_rate(model: Path) -> int:
    """Piper voices keep their rate in <voice>.onnx.json under audio.sample_rate."""
    config_path = derive_config_path(model)
    sample_rate = PIPER_DEFAULT_SAMPLE_RATE
    try:
        sample_rate = int(json.loads(config_path.read_text(encoding="utf-8"))["audio"]["sample_rate"])
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("couldn't read audio.sample_rate from %s, assuming %d Hz", config_path, sample_rate)
    return sample_rate


def build_player_command(device: str | None, raw_sample_rate: int | None = None) -> list[str]:
    """aplay reads stdin: a WAV from espeak-ng, or headerless 16-bit mono audio from Piper."""
    command = [PLAYER_PROGRAM, "-q"]
    if device:
        command += ["-D", device]
    if raw_sample_rate is not None:
        command += ["-r", str(raw_sample_rate), "-f", PIPER_SAMPLE_FORMAT, "-t", "raw", "-"]
    return command


def build_espeak_job(text: str, device: str | None) -> SpeechJob:
    job = SpeechJob(
        synth_name=ESPEAK_PROGRAM,
        synth_command=[ESPEAK_PROGRAM, "--stdout", "-v", ESPEAK_VOICE, "-s", str(ESPEAK_WORDS_PER_MINUTE), "--stdin"],
        player_command=build_player_command(device),
        text_input=encode_text(text),
    )
    return job


def build_piper_job(text: str, model: Path, sample_rate: int, device: str | None) -> SpeechJob:
    job = SpeechJob(
        synth_name=PIPER,
        # The venv's own Python, not a `piper` on PATH: the service's PATH doesn't include .venv/bin,
        # and Debian's apt package called "piper" is an unrelated gaming-mouse app.
        synth_command=[sys.executable, "-m", "piper", "--model", str(model), "--output-raw"],
        player_command=build_player_command(device, raw_sample_rate=sample_rate),
        text_input=encode_text(text),
    )
    return job


def is_piper_installed() -> bool:
    """True when piper-tts is installed for the Python running the app (the dashboard's venv)."""
    installed = True
    try:
        importlib.metadata.distribution(PIPER_PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        installed = False
    return installed


def find_piper_problem(model: Path | None, piper_installed: Callable[[], bool]) -> str | None:
    problem = None
    if not piper_installed():
        problem = f"{PIPER_PACKAGE} isn't installed in the dashboard's venv (.venv/bin/pip install {PIPER_PACKAGE})"
    elif model is None:
        problem = f"{PIPER_MODEL_ENV} isn't set"
    elif not model.is_file():
        problem = f"there's no Piper voice at {model}"
    elif not derive_config_path(model).is_file():
        problem = f"{derive_config_path(model)} is missing (Piper needs the .onnx.json next to the .onnx)"
    return problem


def find_problem(
    settings: VoiceSettings,
    find_program: Callable[[str], str | None] = shutil.which,
    piper_installed: Callable[[], bool] = is_piper_installed,
) -> str | None:
    """Why the chosen voice can't run, or None when it can (or when it's off anyway)."""
    problem = None
    if settings.backend not in BACKENDS:
        problem = f"{VOICE_ENV}={settings.backend!r} isn't one of {', '.join(BACKENDS)}"
    elif settings.backend != OFF and find_program(PLAYER_PROGRAM) is None:
        problem = f"{PLAYER_PROGRAM} isn't installed (sudo apt install alsa-utils)"
    elif settings.backend == ESPEAK and find_program(ESPEAK_PROGRAM) is None:
        problem = f"{ESPEAK_PROGRAM} isn't installed (sudo apt install espeak-ng)"
    elif settings.backend == PIPER:
        problem = find_piper_problem(settings.piper_model, piper_installed)
    return problem


def summarize_error_output(stderr: bytes) -> str:
    lines = stderr.decode("utf-8", errors="replace").strip().splitlines()
    summary = lines[-1].strip() if lines else "no error output"
    return summary


def run_step(
    name: str,
    command: list[str],
    input_bytes: bytes,
    timeout_s: float,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> bytes:
    """Runs one program to the end and returns its stdout. subprocess.run kills it if it passes timeout_s."""
    try:
        result = run(command, input=input_bytes, capture_output=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as error:
        raise SpeechError(f"{name} took longer than {timeout_s:g} s and was killed") from error
    except OSError as error:
        raise SpeechError(f"couldn't start {name}: {error}") from error
    if result.returncode != 0:
        raise SpeechError(f"{name} failed (exit code {result.returncode}): {summarize_error_output(result.stderr)}")
    output = result.stdout
    return output


def run_speech_job(job: SpeechJob, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
    """Makes the whole clip, then plays it.

    Only one program runs at a time, so a stuck synth or a stuck aplay is the only
    process to kill, and the timeout kills it. A phrase is a second or two of audio,
    so waiting for the whole clip costs next to nothing.
    """
    audio = run_step(job.synth_name, job.synth_command, job.text_input, STEP_TIMEOUT_S, run)
    run_step(PLAYER_PROGRAM, job.player_command, audio, STEP_TIMEOUT_S, run)


def discard_queued(phrases: queue.Queue) -> None:
    try:
        while True:
            phrases.get_nowait()
    except queue.Empty:
        pass


class VoiceAnnouncer:
    """Speaks phrases one at a time on a background thread, so say() never blocks the caller.

    For the status API: backend is what's actually in use ("off" after a fallback),
    enabled is backend != "off", and problem says why the chosen voice couldn't run.
    """

    def __init__(
        self,
        settings: VoiceSettings | None = None,
        runner: Callable[[SpeechJob], None] = run_speech_job,
        find_program: Callable[[str], str | None] = shutil.which,
        piper_installed: Callable[[], bool] = is_piper_installed,
    ) -> None:
        self._settings = read_settings() if settings is None else settings
        self._runner = runner
        self.problem = find_problem(self._settings, find_program, piper_installed)
        if self.problem is not None:
            logger.error("voice %r can't run, so it stays off: %s", self._settings.backend, self.problem)
        self.backend = OFF if self.problem is not None else self._settings.backend
        self.enabled = self.backend != OFF
        self._sample_rate = (
            read_sample_rate(self._settings.piper_model) if self.backend == PIPER else PIPER_DEFAULT_SAMPLE_RATE
        )
        self._lock = threading.Lock()
        self._phrases: queue.Queue[str | None] | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self.enabled and self._thread is None:
                self._phrases = queue.Queue(maxsize=QUEUE_SIZE)
                self._thread = threading.Thread(
                    target=self._speak_queued,
                    args=(self._phrases,),
                    name="voice",
                    daemon=True,
                )
                self._thread.start()
        if self.enabled:
            device = self._settings.audio_device or "ALSA's default device"
            logger.info("voice on: %s through aplay on %s", self.backend, device)
        else:
            logger.info("voice off: phrases only go to the log")

    def stop(self) -> None:
        """Drops anything still queued and waits only briefly for the phrase being spoken."""
        with self._lock:
            thread = self._thread
            if thread is not None:
                discard_queued(self._phrases)
                # None tells the worker to finish, and wakes it if it's waiting on an empty queue.
                self._phrases.put_nowait(None)
                self._thread = None
                self._phrases = None
        if thread is not None:
            thread.join(timeout=STOP_JOIN_TIMEOUT_S)

    def say(self, text: str) -> bool:
        """Queues a phrase and returns right away.

        False means it was dropped: the voice is off (it's logged instead), the text
        was blank, the voice isn't running, or QUEUE_SIZE phrases are already waiting.
        """
        phrase = clean_text(text)
        queued = False
        if phrase and not self.enabled:
            logger.info("voice off, would say: %r", phrase)
        elif phrase:
            queued = self._enqueue(phrase)
        return queued

    def _enqueue(self, phrase: str) -> bool:
        queued = False
        with self._lock:
            if self._phrases is None:
                logger.warning("voice isn't running, dropped %r", phrase)
            else:
                try:
                    self._phrases.put_nowait(phrase)
                    queued = True
                except queue.Full:
                    logger.info("voice is busy, dropped %r", phrase)
        return queued

    def _speak_queued(self, phrases: queue.Queue) -> None:
        while (phrase := phrases.get()) is not None:
            self._speak(phrase)

    def _speak(self, phrase: str) -> None:
        try:
            self._runner(self._build_job(phrase))
        except SpeechError as error:
            logger.error("voice couldn't say %r: %s", phrase, error)
        except Exception:
            logger.exception("voice broke while saying %r, carrying on", phrase)

    def _build_job(self, phrase: str) -> SpeechJob:
        device = self._settings.audio_device
        if self.backend == PIPER:
            job = build_piper_job(phrase, self._settings.piper_model, self._sample_rate, device)
        else:
            job = build_espeak_job(phrase, device)
        return job
