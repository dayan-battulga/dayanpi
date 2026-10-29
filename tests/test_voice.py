import json
import logging
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from dayanpi.hardware import voice
from dayanpi.hardware.voice import SpeechError, SpeechJob, VoiceAnnouncer, VoiceSettings

DEVICE = "plughw:CARD=Device,DEV=0"
WAIT_S = 5.0
VOICE_CONFIG = json.dumps({"audio": {"sample_rate": 16000, "quality": "medium"}, "espeak": {"voice": "en-us"}})


def decode_phrase(job: SpeechJob) -> str:
    phrase = job.text_input.decode("utf-8").strip()
    return phrase


def collect_errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    errors = [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]
    return errors


class FakeRunner:
    """Stands in for run_speech_job: records each job, can hold it until released, can fail it."""

    def __init__(self, hold: bool = False, failures: dict[str, Exception] | None = None) -> None:
        self.jobs: list[SpeechJob] = []
        self.failures = failures or {}
        self.release = threading.Event()
        if not hold:
            self.release.set()
        self._changed = threading.Condition()

    def __call__(self, job: SpeechJob) -> None:
        with self._changed:
            self.jobs.append(job)
            self._changed.notify_all()
        self.release.wait(timeout=WAIT_S)
        failure = self.failures.get(decode_phrase(job))
        if failure is not None:
            raise failure

    def wait_for_jobs(self, count: int) -> bool:
        with self._changed:
            reached = self._changed.wait_for(lambda: len(self.jobs) >= count, timeout=WAIT_S)
        return reached

    def list_phrases(self) -> list[str]:
        phrases = [decode_phrase(job) for job in self.jobs]
        return phrases


@dataclass
class VoiceRig:
    announcer: VoiceAnnouncer
    runner: FakeRunner


def make_finder(*missing: str) -> Callable[[str], str | None]:
    """A stand-in for shutil.which where only the named programs are missing."""

    def find(name: str) -> str | None:
        found = None if name in missing else f"/usr/bin/{name}"
        return found

    return find


def write_voice(folder: Path, config_text: str | None) -> Path:
    """A fake Piper voice: a dummy .onnx, plus its .onnx.json unless config_text is None."""
    model = folder / "en_US-test-medium.onnx"
    model.write_bytes(b"not a real model")
    if config_text is not None:
        model.with_name(model.name + ".json").write_text(config_text)
    return model


@pytest.fixture
def make_voice():
    """Builds announcers with a fake runner and fake program lookups, and stops them all afterwards."""
    rigs: list[VoiceRig] = []

    def build(
        backend: str = voice.ESPEAK,
        runner: FakeRunner | None = None,
        model: Path | None = None,
        device: str | None = DEVICE,
        missing_programs: tuple[str, ...] = (),
        piper_installed: bool = True,
    ) -> VoiceRig:
        rig_runner = runner or FakeRunner()
        announcer = VoiceAnnouncer(
            VoiceSettings(backend=backend, piper_model=model, audio_device=device),
            runner=rig_runner,
            find_program=make_finder(*missing_programs),
            piper_installed=lambda: piper_installed,
        )
        rig = VoiceRig(announcer=announcer, runner=rig_runner)
        rigs.append(rig)
        return rig

    yield build
    for rig in rigs:
        rig.announcer.stop()
        rig.runner.release.set()


def test_settings_default_to_off():
    assert voice.read_settings({}) == VoiceSettings(backend="off", piper_model=None, audio_device=None)


def test_settings_tidy_up_the_env_values(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = voice.read_settings(
        {
            "DAYANPI_VOICE": " Piper ",
            "DAYANPI_PIPER_MODEL": "~/voices/en_US-lessac-medium.onnx",
            "DAYANPI_AUDIO_DEVICE": DEVICE,
        }
    )
    assert settings.backend == "piper"
    assert settings.piper_model == tmp_path / "voices" / "en_US-lessac-medium.onnx"
    assert settings.audio_device == DEVICE


def test_off_only_logs_and_runs_nothing(make_voice, caplog):
    caplog.set_level(logging.INFO, logger="dayanpi.hardware.voice")
    rig = make_voice(backend=voice.OFF)
    rig.announcer.start()

    assert rig.announcer.say("Phone down.") is False

    assert rig.announcer.enabled is False
    assert rig.announcer.backend == "off"
    assert rig.announcer.problem is None
    assert "would say: 'Phone down.'" in caplog.text
    assert rig.runner.jobs == []


@pytest.mark.parametrize(
    ("device", "player_command"),
    [
        (None, ["aplay", "-q"]),
        (DEVICE, ["aplay", "-q", "-D", DEVICE]),
    ],
)
def test_espeak_job_pipes_a_wav_into_aplay(device, player_command):
    job = voice.build_espeak_job("Phone down.", device)
    assert job.synth_name == "espeak-ng"
    assert job.synth_command == ["espeak-ng", "--stdout", "-v", "en-us", "-s", "165", "--stdin"]
    assert job.player_command == player_command
    assert job.text_input == b"Phone down.\n"
    assert job.timeout_s == voice.STEP_TIMEOUT_S


@pytest.mark.parametrize(("device", "device_args"), [(None, []), (DEVICE, ["-D", DEVICE])])
def test_piper_job_pipes_raw_audio_into_aplay(device, device_args):
    model = Path("/home/dayoon/piper-voices/en_US-lessac-medium.onnx")
    job = voice.build_piper_job("Break's over.", model, 22050, device)
    assert job.synth_name == "piper"
    assert job.synth_command == [sys.executable, "-m", "piper", "--model", str(model), "--output-raw"]
    assert job.player_command == ["aplay", "-q", *device_args, "-r", "22050", "-f", "S16_LE", "-t", "raw", "-"]
    assert job.text_input == "Break's over.\n".encode("utf-8")


def test_sample_rate_comes_from_the_voice_config(tmp_path):
    assert voice.read_sample_rate(write_voice(tmp_path, VOICE_CONFIG)) == 16000


@pytest.mark.parametrize("config_text", [None, "{}", '{"audio": {"quality": "medium"}}', "not json"])
def test_sample_rate_falls_back_to_22050(tmp_path, config_text):
    assert voice.read_sample_rate(write_voice(tmp_path, config_text)) == 22050


def test_piper_plays_at_the_voice_rate(make_voice, tmp_path):
    model = write_voice(tmp_path, VOICE_CONFIG)
    rig = make_voice(backend=voice.PIPER, model=model)
    rig.announcer.start()

    assert rig.announcer.enabled is True
    assert rig.announcer.backend == "piper"
    assert rig.announcer.say("Break's over.") is True
    assert rig.runner.wait_for_jobs(1)

    job = rig.runner.jobs[0]
    assert str(model) in job.synth_command
    assert job.player_command == ["aplay", "-q", "-D", DEVICE, "-r", "16000", "-f", "S16_LE", "-t", "raw", "-"]


def test_say_drops_phrases_once_the_queue_is_full(make_voice):
    rig = make_voice(runner=FakeRunner(hold=True))
    rig.announcer.start()

    assert rig.announcer.say("one") is True
    assert rig.runner.wait_for_jobs(1)
    assert [rig.announcer.say(phrase) for phrase in ("two", "three", "four")] == [True, True, True]
    assert rig.announcer.say("five") is False


def test_say_drops_blank_text(make_voice):
    rig = make_voice()
    rig.announcer.start()
    assert rig.announcer.say(" \n\t ") is False
    assert rig.runner.jobs == []


def test_stop_returns_quickly_and_skips_queued_phrases(make_voice, monkeypatch):
    monkeypatch.setattr(voice, "STOP_JOIN_TIMEOUT_S", 0.2)
    rig = make_voice(runner=FakeRunner(hold=True))
    rig.announcer.start()
    rig.announcer.say("one")
    assert rig.runner.wait_for_jobs(1)
    rig.announcer.say("two")
    rig.announcer.say("three")
    worker = rig.announcer._thread

    started = time.monotonic()
    rig.announcer.stop()
    assert time.monotonic() - started < 1.0

    rig.runner.release.set()
    worker.join(timeout=WAIT_S)
    assert not worker.is_alive()
    assert rig.runner.list_phrases() == ["one"]
    assert rig.announcer.say("four") is False


def test_failures_are_logged_and_the_worker_keeps_going(make_voice, caplog):
    caplog.set_level(logging.INFO, logger="dayanpi.hardware.voice")
    runner = FakeRunner(
        failures={
            "busy": SpeechError("aplay failed (exit code 1): aplay: main:850: audio open error: Device or resource busy"),
            "stuck": SpeechError("aplay took longer than 20 s and was killed"),
            "surprise": RuntimeError("something nobody expected"),
        }
    )
    rig = make_voice(runner=runner)
    rig.announcer.start()

    for count, phrase in enumerate(("busy", "stuck", "surprise", "fine"), start=1):
        assert rig.announcer.say(phrase) is True
        assert rig.runner.wait_for_jobs(count)

    errors = collect_errors(caplog)
    assert len(errors) == 3
    assert "Device or resource busy" in errors[0]
    assert "was killed" in errors[1]
    assert "'surprise'" in errors[2]
    assert rig.runner.list_phrases() == ["busy", "stuck", "surprise", "fine"]


def test_missing_piper_voice_falls_back_to_off_with_one_error(make_voice, caplog, tmp_path):
    caplog.set_level(logging.INFO, logger="dayanpi.hardware.voice")
    missing = tmp_path / "nowhere.onnx"
    rig = make_voice(backend=voice.PIPER, model=missing)
    rig.announcer.start()

    for _ in range(3):
        assert rig.announcer.say("Phone down.") is False

    errors = collect_errors(caplog)
    assert len(errors) == 1
    assert str(missing) in errors[0]
    assert rig.announcer.enabled is False
    assert rig.announcer.backend == "off"
    assert "would say: 'Phone down.'" in caplog.text
    assert rig.runner.jobs == []


def test_piper_voice_without_its_config_stays_off(make_voice, tmp_path):
    rig = make_voice(backend=voice.PIPER, model=write_voice(tmp_path, config_text=None))
    assert rig.announcer.backend == "off"
    assert "en_US-test-medium.onnx.json is missing" in rig.announcer.problem


@pytest.mark.parametrize(
    ("backend", "missing_programs", "piper_installed", "has_model", "expected"),
    [
        ("espeak", ("espeak-ng",), True, True, "sudo apt install espeak-ng"),
        ("piper", ("aplay",), True, True, "sudo apt install alsa-utils"),
        ("piper", (), False, True, "pip install piper-tts"),
        ("piper", (), True, False, "DAYANPI_PIPER_MODEL isn't set"),
        ("espek", (), True, True, "DAYANPI_VOICE='espek'"),
    ],
)
def test_voice_that_cannot_run_stays_off(
    make_voice, tmp_path, backend, missing_programs, piper_installed, has_model, expected
):
    model = write_voice(tmp_path, VOICE_CONFIG) if has_model else None
    rig = make_voice(backend=backend, model=model, missing_programs=missing_programs, piper_installed=piper_installed)
    assert rig.announcer.enabled is False
    assert rig.announcer.backend == "off"
    assert expected in rig.announcer.problem


def test_weird_text_reaches_the_synth_as_plain_stdin(make_voice):
    rig = make_voice()
    rig.announcer.start()
    weird = "He said \"hi\"; rm -rf ~ && echo $(whoami) `id` | tee x\nnext line\t\x00\x1b[31m — ünïcödé 🙂 'quoted'"

    assert rig.announcer.say(weird) is True
    assert rig.runner.wait_for_jobs(1)

    job = rig.runner.jobs[0]
    expected = "He said \"hi\"; rm -rf ~ && echo $(whoami) `id` | tee x next line [31m — ünïcödé 🙂 'quoted'"
    assert job.text_input == (expected + "\n").encode("utf-8")
    assert not any("whoami" in part for part in job.synth_command + job.player_command)


@dataclass
class RunCall:
    command: list[str]
    options: dict


class FakeRun:
    """Stands in for subprocess.run: hands out the given results (or raises the given errors) in order."""

    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[RunCall] = []

    def __call__(self, command: list[str], **options) -> subprocess.CompletedProcess:
        self.calls.append(RunCall(command=command, options=options))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def make_result(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> subprocess.CompletedProcess:
    result = subprocess.CompletedProcess(args=["fake"], returncode=returncode, stdout=stdout, stderr=stderr)
    return result


def test_runner_feeds_stdin_through_and_never_uses_a_shell():
    run = FakeRun([make_result(stdout=b"RIFF fake wav"), make_result()])
    job = voice.build_espeak_job("a \"quoted\"; $(thing)", DEVICE)

    voice.run_speech_job(job, run=run)

    assert [call.command for call in run.calls] == [job.synth_command, job.player_command]
    assert run.calls[0].options["input"] == job.text_input
    assert run.calls[1].options["input"] == b"RIFF fake wav"
    for call in run.calls:
        assert "shell" not in call.options
        assert call.options["timeout"] == job.timeout_s
        assert call.options["capture_output"] is True


@pytest.mark.parametrize(
    ("outcomes", "expected", "call_count"),
    [
        (
            [make_result(returncode=1, stderr=b"some warning\nerror: voice 'en-us' not found\n")],
            "espeak-ng failed (exit code 1): error: voice 'en-us' not found",
            1,
        ),
        (
            [
                make_result(stdout=b"audio"),
                make_result(returncode=1, stderr=b"ALSA lib ...\naplay: main:850: audio open error: Device or resource busy\n"),
            ],
            "aplay failed (exit code 1): aplay: main:850: audio open error: Device or resource busy",
            2,
        ),
        (
            [make_result(stdout=b"audio"), subprocess.TimeoutExpired(cmd=["aplay"], timeout=20)],
            "aplay took longer than 20 s and was killed",
            2,
        ),
        (
            [subprocess.TimeoutExpired(cmd=["espeak-ng"], timeout=20)],
            "espeak-ng took longer than 20 s and was killed",
            1,
        ),
        (
            [FileNotFoundError(2, "No such file or directory", "espeak-ng")],
            "couldn't start espeak-ng: [Errno 2] No such file or directory: 'espeak-ng'",
            1,
        ),
        ([make_result(returncode=-9)], "espeak-ng failed (exit code -9): no error output", 1),
    ],
)
def test_runner_turns_failures_into_speech_errors(outcomes, expected, call_count):
    run = FakeRun(outcomes)
    with pytest.raises(SpeechError) as caught:
        voice.run_speech_job(voice.build_espeak_job("Phone down.", None), run=run)
    assert str(caught.value) == expected
    assert len(run.calls) == call_count
