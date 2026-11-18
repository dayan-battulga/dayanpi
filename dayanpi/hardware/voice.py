"""Says short phrases out loud ("Phone down.", "Break's over.") through a USB speaker.

The trap: dayanpi runs as a systemd *system* service, and a system service can't
reach the desktop's PipeWire/PulseAudio session. So every phrase plays straight
through ALSA's aplay, on DAYANPI_AUDIO_DEVICE when it's set (for example
plughw:CARD=Device,DEV=0), or on ALSA's default device when it isn't.

Settings come from the environment (/etc/dayanpi.env on the Pi):
- DAYANPI_VOICE: "off" (the default, which only logs that it would have said something)
  or "piper" (piper-tts from pip, in the venv)
- DAYANPI_PIPER_MODEL: path to a Piper voice .onnx, with its .onnx.json next to it
- DAYANPI_AUDIO_DEVICE: the ALSA device aplay plays on

If the chosen voice can't run, it logs one error and stays off. The app carries on.

A phrase can also become a clip instead (render): Piper makes the same audio, it's wrapped into a WAV
in memory, and someone's own page plays it ("This computer" in Settings → Voice and bedtime). ClipShelf
keeps each person's latest clip for CLIP_KEEP_S at most and hands it out once. Clips never touch the disk
and are never logged.

No phrase's words are ever logged either: a peace sign's message is someone's to-dos, and a nudge names who sent
it. The callouts' fixed lines are in the app's own "focus callout" log line.
"""

import importlib.metadata
import io
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import wave
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

VOICE_ENV = "DAYANPI_VOICE"
PIPER_MODEL_ENV = "DAYANPI_PIPER_MODEL"
AUDIO_DEVICE_ENV = "DAYANPI_AUDIO_DEVICE"

OFF = "off"
PIPER = "piper"
BACKENDS = (OFF, PIPER)

QUEUE_SIZE = 3
STEP_TIMEOUT_S = 20.0
STOP_JOIN_TIMEOUT_S = 1.0
CLIP_KEEP_S = 60.0  # a clip nobody fetched in this long is gone

PLAYER_PROGRAM = "aplay"
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


ClipSink = Callable[[bytes], None]


@dataclass
class Clip:
    wav: bytes
    made_at: float


@dataclass
class SpeechJob:
    """One phrase: Piper turns text_input into audio, then aplay plays it."""

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


def build_player_command(device: str | None, sample_rate: int) -> list[str]:
    """aplay reads Piper's headerless 16-bit mono audio from stdin."""
    command = [PLAYER_PROGRAM, "-q"]
    if device:
        command += ["-D", device]
    command += ["-r", str(sample_rate), "-f", PIPER_SAMPLE_FORMAT, "-t", "raw", "-"]
    return command


def build_piper_job(text: str, model: Path, sample_rate: int, device: str | None) -> SpeechJob:
    job = SpeechJob(
        # The venv's own Python, not a `piper` on PATH: the service's PATH doesn't include .venv/bin,
        # and Debian's apt package called "piper" is an unrelated gaming-mouse app.
        synth_command=[sys.executable, "-m", "piper", "--model", str(model), "--output-raw"],
        player_command=build_player_command(device, sample_rate),
        # Piper reads the phrase from stdin, so it never ends up on a command line.
        text_input=(text + "\n").encode("utf-8"),
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
    find_program: Callable[[str], str | None],
    piper_installed: Callable[[], bool],
) -> str | None:
    """Why the chosen voice can't run, or None when it can (or when it's off anyway)."""
    problem = None
    if settings.backend not in BACKENDS:
        problem = f"{VOICE_ENV}={settings.backend!r} isn't one of {', '.join(BACKENDS)}"
    elif settings.backend != OFF and find_program(PLAYER_PROGRAM) is None:
        problem = f"{PLAYER_PROGRAM} isn't installed (sudo apt install alsa-utils)"
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
    run: Callable[..., subprocess.CompletedProcess],
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
    audio = run_step(PIPER, job.synth_command, job.text_input, STEP_TIMEOUT_S, run)
    run_step(PLAYER_PROGRAM, job.player_command, audio, STEP_TIMEOUT_S, run)


def wrap_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Piper's raw 16-bit mono audio as a WAV file, in memory."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(sample_rate)
        clip.writeframes(pcm)
    wav = buffer.getvalue()
    return wav


def synthesize_clip(job: SpeechJob, sample_rate: int, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bytes:
    """The same Piper step as run_speech_job, wrapped into a WAV instead of played: nothing is written to disk."""
    audio = run_step(PIPER, job.synth_command, job.text_input, STEP_TIMEOUT_S, run)
    wav = wrap_wav(audio, sample_rate)
    return wav


class ClipShelf:
    """Each person's latest clip, by username, for CLIP_KEEP_S at most. take() hands it out once."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clips: dict[str, Clip] = {}

    def put(self, owner: str, wav: bytes, now: float) -> None:
        with self._lock:
            self._clips[owner] = Clip(wav, now)

    def drop(self, owner: str) -> None:
        with self._lock:
            self._clips.pop(owner, None)

    def has(self, owner: str, now: float) -> bool:
        with self._lock:
            clip = self._clips.get(owner)
            fresh = clip is not None and now - clip.made_at < CLIP_KEEP_S
        return fresh

    def take(self, owner: str, now: float) -> bytes | None:
        with self._lock:
            clip = self._clips.pop(owner, None)
        wav = clip.wav if clip is not None and now - clip.made_at < CLIP_KEEP_S else None
        return wav


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
    is_saying() tells the page whether a phrase is still waiting or playing.
    """

    def __init__(
        self,
        settings: VoiceSettings | None = None,
        runner: Callable[[SpeechJob], None] = run_speech_job,
        find_program: Callable[[str], str | None] = shutil.which,
        piper_installed: Callable[[], bool] = is_piper_installed,
        synthesizer: Callable[[SpeechJob, int], bytes] = synthesize_clip,
    ) -> None:
        self._settings = read_settings() if settings is None else settings
        self._runner = runner
        self._synthesizer = synthesizer
        self.problem = find_problem(self._settings, find_program, piper_installed)
        if self.problem is not None:
            logger.error("voice %r can't run, so it stays off: %s", self._settings.backend, self.problem)
        self.backend = OFF if self.problem is not None else self._settings.backend
        self.enabled = self.backend != OFF
        self._sample_rate = (
            read_sample_rate(self._settings.piper_model) if self.backend == PIPER else PIPER_DEFAULT_SAMPLE_RATE
        )
        self._lock = threading.Lock()
        # (phrase, None) plays on the speaker; (phrase, sink) hands its WAV to sink instead.
        self._phrases: queue.Queue[tuple[str, ClipSink | None] | None] | None = None
        self._thread: threading.Thread | None = None
        self._saying: Counter[str] = Counter()  # phrases queued or playing, until aplay finishes them

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
                self._saying.clear()
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
            logger.info("voice off, would say something (%d characters)", len(phrase))
        elif phrase:
            queued = self._enqueue(phrase, None)
        return queued

    def render(self, text: str, sink: ClipSink) -> bool:
        """Queues a phrase to become a WAV clip, which goes to sink on the voice thread; nothing plays here.

        Behind whatever the speaker is saying, so the Pi only ever runs one Piper. False, and no clip, when the
        voice is off, the text is blank, or the queue is full. The text isn't logged: it's someone's to-dos.
        """
        phrase = clean_text(text)
        queued = bool(phrase) and self.enabled and self._enqueue(phrase, sink)
        return queued

    def _enqueue(self, phrase: str, sink: ClipSink | None) -> bool:
        queued = False
        shown = "a phrase" if sink is None else "a clip"
        with self._lock:
            if self._phrases is None:
                logger.warning("voice isn't running, dropped %s", shown)
            else:
                try:
                    self._phrases.put_nowait((phrase, sink))
                    if sink is None:
                        self._saying[phrase] += 1
                    queued = True
                except queue.Full:
                    logger.info("voice is busy, dropped %s", shown)
        return queued

    def is_saying(self, text: str) -> bool:
        """True from say() until aplay has played the phrase (or it failed), while it waits behind others too."""
        with self._lock:
            saying = self._saying[clean_text(text)] > 0
        return saying

    def _speak_queued(self, phrases: queue.Queue) -> None:
        while (item := phrases.get()) is not None:
            phrase, sink = item
            if sink is None:
                self._speak(phrase)
                self._finish(phrases, phrase)
            else:
                self._render(phrase, sink)

    def _finish(self, phrases: queue.Queue, phrase: str) -> None:
        with self._lock:
            # After stop() the count is gone with its queue; a phrase that was mid-way then doesn't touch the next one's.
            if phrases is self._phrases:
                self._saying[phrase] -= 1
                if self._saying[phrase] <= 0:
                    del self._saying[phrase]

    def _render(self, phrase: str, sink: ClipSink) -> None:
        try:
            sink(self._synthesizer(build_piper_job(phrase, self._settings.piper_model, self._sample_rate, None), self._sample_rate))
        except SpeechError as error:
            logger.error("voice couldn't make a clip: %s", error)
        except Exception:
            logger.exception("voice broke while making a clip, carrying on")

    def _speak(self, phrase: str) -> None:
        try:
            self._runner(build_piper_job(phrase, self._settings.piper_model, self._sample_rate, self._settings.audio_device))
        except SpeechError as error:
            logger.error("voice couldn't say a phrase: %s", error)
        except Exception:
            logger.exception("voice broke while saying a phrase, carrying on")
