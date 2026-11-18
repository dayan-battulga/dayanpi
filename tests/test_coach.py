import json
import logging
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dayanpi.focus.coach import (
    MAX_AGE_S,
    REWRITE_S,
    CoachWriter,
    TodoCoach,
    build_prompt,
    build_system_prompt,
    clean_message,
    collect_facts,
    describe_todos,
)
from dayanpi.focus.todos import TodoList
from dayanpi.hardware.llm import OllamaClient, read_llm_model


def at(hour: int, minute: int = 0, day: int = 15) -> float:
    moment = datetime(2026, 11, day, hour, minute).timestamp()
    return moment


def make_snapshot(open_texts: list[str] = (), done: list[tuple[str, int]] = ()) -> dict:
    snapshot = {
        "current": None,
        "open": [{"id": str(index), "text": text, "seconds": 0, "done_at": None} for index, text in enumerate(open_texts)],
        "done": [{"id": f"d{index}", "text": text, "seconds": seconds, "done_at": 1.0} for index, (text, seconds) in enumerate(done)],
    }
    return snapshot


THREE = ["finish the report", "reply to emails", "do laundry"]
EIGHT = ["one", "two", "three", "four", "five", "six", "seven", "eight"]


# ----- the facts -----


@pytest.mark.parametrize(
    ("now", "bedtime", "clock", "minutes_to_bed"),
    [
        (at(15, 0), 0, "3 p.m.", 9 * 60),
        (at(23, 50), 0, "11:50 p.m.", 10),
        (at(0, 30, day=16), 0, "12:30 a.m.", None),
        (at(4, 59, day=16), 0, "4:59 a.m.", None),
        (at(5, 0), 0, "5 a.m.", 19 * 60),
        (at(18, 0), 22 * 60 + 30, "6 p.m.", 4 * 60 + 30),
        (at(23, 0), 22 * 60 + 30, "11 p.m.", None),
        (at(23, 0), 90, "11 p.m.", 150),
    ],
    ids=["afternoon", "11:50 p.m.", "past bedtime", "still past bedtime at 4:59", "morning", "custom bedtime", "past a custom bedtime", "bedtime after midnight"],
)
def test_the_time_and_the_time_to_bed(now, bedtime, clock, minutes_to_bed):
    facts = collect_facts(make_snapshot(), now, bedtime)
    assert (facts.clock, facts.minutes_to_bed) == (clock, minutes_to_bed)


def test_the_to_dos_in_the_facts():
    facts = collect_facts(make_snapshot(EIGHT, [("read  chapter\n3", 2400)] * 6), at(15), 0)
    assert facts.open_texts == ("one", "two", "three", "four", "five")
    assert facts.open_count == 8
    assert [(item.text, item.seconds) for item in facts.done] == [("read chapter 3", 2400)] * 5
    assert facts.done_count == 6


# ----- the template -----


@pytest.mark.parametrize(
    ("now", "open_texts", "done", "sentence"),
    [
        (
            at(18),
            THREE,
            [("read chapter 3", 2400)],
            "It's 6 p.m., about 6 hours until bed. You have 3 things to do: finish the report, reply to emails, and do laundry. "
            "Done today: read chapter 3 in 40 minutes.",
        ),
        (at(15), [], [], "It's 3 p.m., about 9 hours until bed. Your to-do list is empty."),
        (at(23, 58), ["finish the report"], [], "It's 11:58 p.m., less than 5 minutes until bed. You have 1 thing to do: finish the report."),
        (
            at(0, 30, day=16),
            ["finish the report", "reply to emails"],
            [("water the plants", 20)],
            "It's 12:30 a.m., past your bedtime. You have 2 things to do: finish the report and reply to emails. "
            "Done today: water the plants. Time to wrap up for tonight.",
        ),
        (
            at(15),
            EIGHT,
            [("a", 60)] * 6,
            "It's 3 p.m., about 9 hours until bed. You have 8 things to do: one, two, three, four, five, and 3 more. "
            "Done today: a in 1 minute, a in 1 minute, a in 1 minute, a in 1 minute, a in 1 minute, and 1 more.",
        ),
    ],
    ids=["evening", "empty", "minutes left", "past bedtime", "long lists"],
)
def test_the_template(now, open_texts, done, sentence):
    assert describe_todos(collect_facts(make_snapshot(open_texts, done), now, 0)) == sentence


# ----- checking what the LLM wrote -----

PROMPT = build_prompt(collect_facts(make_snapshot(THREE, [("read chapter 3", 2400)]), at(18), 0))


def test_the_prompt_holds_only_the_facts():
    assert PROMPT == (
        "Time now: 6 p.m.\n"
        "Time until bed: about 6 hours\n"
        "Open to-dos (3): finish the report; reply to emails; do laundry\n"
        "Done today (1): read chapter 3 (took 40 minutes)"
    )


@pytest.mark.parametrize(
    ("open_texts", "done", "sentences"),
    [(THREE, [], "2 or 3"), (THREE + ["call mom"], [], "3 or 4"), (THREE, [("read chapter 3", 2400)], "3 or 4")],
    ids=["3 to-dos", "4 open", "3 open and 1 done"],
)
def test_more_to_dos_get_more_sentences(open_texts, done, sentences):
    system = build_system_prompt(collect_facts(make_snapshot(open_texts, done), at(18), 0))
    assert f"Use {sentences} short sentences." in system


GOOD = "It's 6 p.m., so you've got about 6 hours before bed. Three things left: the report, emails and laundry. You already knocked out the reading in 40 minutes, so you can definitely finish these."


@pytest.mark.parametrize(
    ("reply", "cleaned"),
    [
        (GOOD, GOOD),
        (f'  "{GOOD}"\n', GOOD),
        ("It's 6:00 p.m.\nAbout 6 hours to go. You've got this.", "It's 6:00 p.m. About 6 hours to go. You've got this."),
        ("", None),
        (None, None),
        ("Here's your list:\n- finish the report\n- reply to emails", None),
        ("1. finish the report\n2. reply to emails", None),
        ("You've got this! 💪 Three things left.", None),
        ("**Three things** left, about 6 hours.", None),
        ("It's 6 p.m. and you have 4 things left.", None),
        ("Keep going. " * 10, None),
        ("Great work today. " + "You have plenty of time left tonight to get everything done " * 8, None),
    ],
    ids=["good", "quoted and padded", "6:00 and a line break", "empty", "no reply", "dash list", "numbered list", "emoji", "markdown", "made-up number", "too many sentences", "too long"],
)
def test_clean_message(reply, cleaned):
    assert clean_message(reply, PROMPT) == cleaned


# ----- the LLM path, with a fake Ollama on 127.0.0.1 -----


class FakeOllama:
    """A tiny HTTP server standing in for Ollama: records each request and answers the way mode says."""

    def __init__(self) -> None:
        self.mode = "ok"
        self.reply = GOOD
        self.requests: list[dict] = []
        self.in_flight = 0
        self.most_at_once = 0  # the most requests it was answering at the same time
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                fake.requests.append({"path": self.path, "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
                with fake.lock:
                    fake.in_flight += 1
                    fake.most_at_once = max(fake.most_at_once, fake.in_flight)
                time.sleep(1.0 if fake.mode == "slow" else 0.05)
                with fake.lock:
                    fake.in_flight -= 1
                status, body = (404, {"error": "model 'nope' not found"}) if fake.mode == "missing" else (200, {"response": fake.reply, "done": True})
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except OSError:
                    pass  # the client gave up waiting

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def ollama():
    fake = FakeOllama()
    yield fake
    fake.close()


def make_coach(tmp_path, port: int | None, clock: list[float], timeout_s: float = 5.0) -> TodoCoach:
    """Three open to-dos and "read chapter 3" done today in 40 minutes, the facts GOOD talks about."""
    items = [{"id": str(index), "text": text, "created_at": clock[0], "done_at": None, "seconds": 0.0} for index, text in enumerate(THREE)]
    items.append({"id": "read", "text": "read chapter 3", "created_at": clock[0], "done_at": clock[0] - 60, "seconds": 2400.0})
    (tmp_path / "todos.json").write_text(json.dumps({"current": None, "items": items}))
    todos = TodoList(tmp_path / "todos.json")
    llm = None if port is None else OllamaClient("llama3.2:1b", port=port, timeout_s=timeout_s)
    coach = TodoCoach(todos, lambda: 0, llm, clock=lambda: clock[0])
    return coach


def test_a_good_reply_is_written_ahead_and_spoken(tmp_path, ollama):
    clock = [at(18)]
    coach = make_coach(tmp_path, ollama.port, clock)
    coach.tick()
    message = coach.pick(clock[0] + 10)
    assert (message.source, message.text) == ("llm", GOOD)
    request = ollama.requests[0]
    assert request["path"] == "/api/generate"
    body = request["body"]
    assert (body["model"], body["stream"], body["keep_alive"], body["options"]["num_thread"]) == ("llama3.2:1b", False, "15m", 2)
    assert "Use 3 or 4 short sentences." in body["system"], "3 open and 1 done"
    assert "Open to-dos (3): finish the report; reply to emails; do laundry" in body["prompt"]


def test_nothing_changed_means_no_new_draft_until_it_is_due(tmp_path, ollama):
    clock = [at(18)]
    coach = make_coach(tmp_path, ollama.port, clock)
    coach.tick()
    clock[0] += 60
    coach.tick()
    assert len(ollama.requests) == 1
    clock[0] = at(18) + REWRITE_S
    coach.tick()
    assert len(ollama.requests) == 2, "a fresh draft every 4 minutes"


def test_a_changed_list_speaks_the_template_until_the_new_draft_is_ready(tmp_path, ollama):
    clock = [at(18)]
    coach = make_coach(tmp_path, ollama.port, clock)
    coach.tick()
    coach._todos.add("call mom", clock[0])
    message = coach.pick(clock[0])
    assert message.source == "template" and "call mom" in message.text, "the old draft doesn't know about it"
    ollama.reply = "It's 6 p.m., about 6 hours until bed. Four things left, including calling mom. You've got this."
    coach.tick()
    assert coach.pick(clock[0]).source == "llm"


def test_a_draft_older_than_five_minutes_is_not_spoken(tmp_path, ollama):
    clock = [at(18)]
    coach = make_coach(tmp_path, ollama.port, clock)
    coach.tick()
    assert coach.pick(at(18) + MAX_AGE_S - 1).source == "llm"
    assert coach.pick(at(18) + MAX_AGE_S).source == "template"


@pytest.mark.parametrize("mode", ["slow", "garbage", "missing", "down"])
def test_anything_but_a_good_reply_speaks_the_template(tmp_path, ollama, mode, caplog):
    clock = [at(18)]
    ollama.mode = mode
    ollama.reply = "- finish the report\n- reply to emails" if mode == "garbage" else GOOD
    port = ollama.port
    if mode == "down":
        ollama.close()  # nothing listening any more
    coach = make_coach(tmp_path, port, clock, timeout_s=0.3)
    with caplog.at_level(logging.INFO):
        coach.tick()
    message = coach.pick(clock[0])
    assert message.source == "template"
    assert message.text.startswith("It's 6 p.m., about 6 hours until bed. You have 3 things to do:")
    assert "peace sign:" in caplog.text
    assert "finish the report" not in caplog.text, "a to-do never goes in the journal"
    if mode == "missing":
        assert "404" in coach.llm.problem


def test_no_model_set_means_the_template(tmp_path):
    clock = [at(18)]
    coach = make_coach(tmp_path, None, clock)
    assert coach.pick(clock[0]).source == "template"
    assert read_llm_model({}) is None
    assert read_llm_model({"DAYANPI_LLM_MODEL": "  "}) is None
    assert read_llm_model({"DAYANPI_LLM_MODEL": " llama3.2:1b "}) == "llama3.2:1b"


def make_desk_coach(folder, port: int, clock: list[float], open_texts: list[str], bedtime: list[int]) -> TodoCoach:
    """One person's coach over their own to-dos and their own bedtime (a list, so a test can change it)."""
    folder.mkdir()
    todos = TodoList(folder / "todos.json")
    for text in open_texts:
        todos.add(text, clock[0])
    coach = TodoCoach(todos, lambda: bedtime[0], OllamaClient("llama3.2:1b", port=port), clock=lambda: clock[0])
    return coach


def test_one_writer_writes_everyones_drafts_one_at_a_time(tmp_path, ollama):
    clock = [at(18)]
    people = {"dayan": ["finish the report"], "sam": ["read chapter 3"], "alex": ["call mom"], "bo": ["do laundry"]}
    coaches = [make_desk_coach(tmp_path / name, ollama.port, clock, texts, [0]) for name, texts in people.items()]
    writer = CoachWriter(lambda: coaches)
    ollama.reply = "It's 6 p.m., about 6 hours until bed. One thing left. You've got this."
    writer.tick()
    prompts = [request["body"]["prompt"] for request in ollama.requests]
    assert ollama.most_at_once == 1, "four people, still one model run at a time"
    assert [coach.pick(clock[0]).source for coach in coaches] == ["llm"] * 4
    assert [prompt.split("\n")[2] for prompt in prompts] == [f"Open to-dos (1): {texts[0]}" for texts in people.values()]
    writer.tick()
    assert len(ollama.requests) == 4, "nothing changed, nothing due"


def test_a_coach_counts_to_its_own_bedtime_as_soon_as_it_changes(tmp_path):
    clock = [at(21)]
    bedtime = [22 * 60]
    todos = TodoList(tmp_path / "todos.json")
    coach = TodoCoach(todos, lambda: bedtime[0], None, clock=lambda: clock[0])
    before = coach.pick(clock[0]).text
    bedtime[0] = 23 * 60 + 30
    after = coach.pick(clock[0]).text
    assert before.startswith("It's 9 p.m., about 1 hour until bed.")
    assert after.startswith("It's 9 p.m., about 2 hours 30 minutes until bed.")


def test_a_writer_without_a_model_writes_nothing(tmp_path):
    clock = [at(18)]
    coach = TodoCoach(TodoList(tmp_path / "todos.json"), lambda: 0, None, clock=lambda: clock[0])
    CoachWriter(lambda: [coach]).tick()
    assert coach.draft is None and coach.pick(clock[0]).source == "template"

