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
FAKE_MODEL = Path("/home/dayoon/piper-voices/en_US-lessac-medium.onnx")
WAIT_S = 5.0
VOICE_CONFIG = json.dumps({"audio": {"sample_rate": 16000, "quality": "medium"}, "espeak": {"voice": "en-us"}})
TEST_VOICE = object()  # make_voice's default: a working fake voice, since None means no voice is set


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
def make_voice(tmp_path):
    """Builds announcers with a fake runner, a fake voice and fake program lookups, and stops them all afterwards."""
    rigs: list[VoiceRig] = []

    def build(
        backend: str = voice.PIPER,
        runner: FakeRunner | None = None,
        model: Path | None | object = TEST_VOICE,
        device: str | None = DEVICE,
        missing_programs: tuple[str, ...] = (),
        piper_installed: bool = True,
    ) -> VoiceRig:
        rig_runner = runner or FakeRunner()
        rig_model = write_voice(tmp_path, VOICE_CONFIG) if model is TEST_VOICE else model
        announcer = VoiceAnnouncer(
            VoiceSettings(backend=backend, piper_model=rig_model, audio_device=device),
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
    assert "voice off, would say something (11 characters)" in caplog.text
    assert "Phone down" not in caplog.text, "never the words"
    assert rig.runner.jobs == []


@pytest.mark.parametrize(("device", "device_args"), [(None, []), (DEVICE, ["-D", DEVICE])])
def test_piper_job_pipes_raw_audio_into_aplay(device, device_args):
    model = Path("/home/dayoon/piper-voices/en_US-lessac-medium.onnx")
    job = voice.build_piper_job("Break's over.", model, 22050, device)
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


def test_is_saying_lasts_from_say_until_the_phrase_is_played_or_fails(make_voice):
    runner = FakeRunner(hold=True, failures={"two": SpeechError("aplay failed")})
    rig = make_voice(runner=runner)
    rig.announcer.start()
    assert not rig.announcer.is_saying("one")
    rig.announcer.say("one")
    rig.announcer.say("two\n")
    assert rig.runner.wait_for_jobs(1)
    assert rig.announcer.is_saying("one") and rig.announcer.is_saying("two"), "two waits behind one"
    runner.release.set()
    deadline = time.monotonic() + WAIT_S
    while (rig.announcer.is_saying("one") or rig.announcer.is_saying("two")) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not rig.announcer.is_saying("one") and not rig.announcer.is_saying("two")
    assert rig.announcer._saying == {}, "finished phrases don't pile up"


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
    assert errors[2] == "voice broke while saying a phrase, carrying on"
    assert "'surprise'" not in caplog.text, "never the words"
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
    assert "voice off, would say something (11 characters)" in caplog.text
    assert "Phone down" not in caplog.text, "never the words"
    assert rig.runner.jobs == []


def test_piper_voice_without_its_config_stays_off(make_voice, tmp_path):
    rig = make_voice(backend=voice.PIPER, model=write_voice(tmp_path, config_text=None))
    assert rig.announcer.backend == "off"
    assert "en_US-test-medium.onnx.json is missing" in rig.announcer.problem


@pytest.mark.parametrize(
    ("backend", "missing_programs", "piper_installed", "has_model", "expected"),
    [
        ("piper", ("aplay",), True, True, "sudo apt install alsa-utils"),
        ("piper", (), False, True, "pip install piper-tts"),
        ("piper", (), True, False, "DAYANPI_PIPER_MODEL isn't set"),
        ("espeak", (), True, True, "DAYANPI_VOICE='espeak' isn't one of off, piper"),
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
    run = FakeRun([make_result(stdout=b"fake raw audio"), make_result()])
    job = voice.build_piper_job("a \"quoted\"; $(thing)", FAKE_MODEL, 22050, DEVICE)

    voice.run_speech_job(job, run=run)

    assert [call.command for call in run.calls] == [job.synth_command, job.player_command]
    assert run.calls[0].options["input"] == job.text_input
    assert run.calls[1].options["input"] == b"fake raw audio"
    for call in run.calls:
        assert "shell" not in call.options
        assert call.options["timeout"] == voice.STEP_TIMEOUT_S
        assert call.options["capture_output"] is True


@pytest.mark.parametrize(
    ("outcomes", "expected", "call_count"),
    [
        (
            [make_result(returncode=1, stderr=b"some warning\nerror: voice 'en-us' not found\n")],
            "piper failed (exit code 1): error: voice 'en-us' not found",
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
            [subprocess.TimeoutExpired(cmd=["piper"], timeout=20)],
            "piper took longer than 20 s and was killed",
            1,
        ),
        (
            [FileNotFoundError(2, "No such file or directory", "python")],
            "couldn't start piper: [Errno 2] No such file or directory: 'python'",
            1,
        ),
        ([make_result(returncode=-9)], "piper failed (exit code -9): no error output", 1),
    ],
)
def test_runner_turns_failures_into_speech_errors(outcomes, expected, call_count):
    run = FakeRun(outcomes)
    with pytest.raises(SpeechError) as caught:
        voice.run_speech_job(voice.build_piper_job("Phone down.", FAKE_MODEL, 22050, None), run=run)
    assert str(caught.value) == expected
    assert len(run.calls) == call_count


def test_a_clip_is_pipers_audio_as_a_wav_in_memory_with_no_file_anywhere(tmp_path, monkeypatch):
    import io
    import wave

    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_run(command, **options):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"\x01\x00" * 800, stderr=b"")

    job = voice.build_piper_job("Phone down.", FAKE_MODEL, 16000, None)
    wav = voice.synthesize_clip(job, 16000, run=fake_run)
    with wave.open(io.BytesIO(wav)) as clip:
        shape = (clip.getnchannels(), clip.getsampwidth(), clip.getframerate(), clip.getnframes())
    assert shape == (1, 2, 16000, 800)
    assert calls == [job.synth_command] and "--output-raw" in calls[0], "Piper only, never aplay or an output file"
    assert list(tmp_path.iterdir()) == []


def test_render_makes_the_clip_on_the_voice_thread_behind_what_the_speaker_says(make_voice, tmp_path):
    rig = make_voice()
    made = []
    rendered = threading.Event()
    rig.announcer._synthesizer = lambda job, rate: made.append((decode_phrase(job), rate)) or b"RIFFclip"
    rig.announcer.start()
    rig.announcer.say("Phone down.")
    assert rig.announcer.render("It's 9 p.m.", lambda wav: rendered.set() if wav == b"RIFFclip" else None, "sam")
    assert rendered.wait(WAIT_S)
    assert rig.runner.list_phrases() == ["Phone down."], "only the speaker's phrase went to aplay"
    assert made == [("It's 9 p.m.", 16000)]
    assert not rig.announcer.is_saying("It's 9 p.m."), "a clip isn't the speaker's to say"


def test_each_person_has_one_clip_at_a_time_and_the_speaker_keeps_its_places(make_voice):
    from dayanpi.auth.accounts import MAX_ACCOUNTS

    assert voice.CLIP_SLOTS == MAX_ACCOUNTS, "a place in the queue for every account's clip"
    rig = make_voice(runner=FakeRunner(hold=True))
    making = threading.Event()
    release = threading.Event()
    made = []

    def make_slowly(job, rate):
        making.set()
        release.wait(WAIT_S)
        made.append(decode_phrase(job))
        return b"RIFFclip"

    rig.announcer._synthesizer = make_slowly
    rig.announcer.start()
    keep = lambda wav: None
    assert rig.announcer.render("sam's first", keep, "sam")
    assert making.wait(WAIT_S)
    assert rig.announcer.render("sam's second", keep, "sam") is False, "one being made is still sam's one"
    assert [rig.announcer.render(f"{name}'s", keep, name) for name in ("dayoon", "bo", "cy")] == [True] * 3
    assert rig.announcer.render("bo's second", keep, "bo") is False, "one waiting too"
    assert [rig.announcer.say(line) for line in ("one", "two", "three")] == [True] * 3, "everyone's clips leave the speaker its places"
    assert rig.announcer.say("four") is False
    release.set()
    rig.runner.release.set()
    assert rig.runner.wait_for_jobs(3)
    deadline = time.monotonic() + WAIT_S
    while len(made) < 4 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert made == ["sam's first", "dayoon's", "bo's", "cy's"]
    while not rig.announcer.render("sam's next", keep, "sam") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "sam" in rig.announcer._clip_owners, "a new one once the last is made"


def test_render_does_nothing_with_the_voice_off(make_voice):
    rig = make_voice(backend=voice.OFF)
    rig.announcer.start()
    assert rig.announcer.render("It's 9 p.m.", lambda wav: pytest.fail("no clip with the voice off"), "sam") is False


def test_the_clip_shelf_hands_out_your_own_clip_once_and_only_for_a_minute():
    shelf = voice.ClipShelf()
    shelf.put("sam", b"sam's", 1000.0)
    shelf.put("bo", b"bo's", 1000.0)
    assert shelf.has("sam", 1000.0 + voice.CLIP_KEEP_S - 1)
    assert shelf.take("sam", 1010.0) == b"sam's"
    assert shelf.take("sam", 1011.0) is None, "gone once it's fetched"
    assert not shelf.has("bo", 1000.0 + voice.CLIP_KEEP_S)
    assert shelf.take("bo", 1000.0 + voice.CLIP_KEEP_S) is None, "gone after a minute"

