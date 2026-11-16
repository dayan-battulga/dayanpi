"""What the peace sign says: a short, encouraging rundown of the time, the time left before bed and the to-dos.

The facts (collect_facts) are the clock, the minutes to bedtime (DAYANPI_BEDTIME, default
00:00), the first SPOKEN_MAX open to-dos and how many more, and what got done today with
the time each took. From 5 a.m. on it counts toward tonight's bedtime; between bedtime and
5 a.m. it's past bedtime.

Two ways to say them:
- describe_todos(): a fixed template, always there.
- An LLM in Ollama (hardware/llm.py, when DAYANPI_LLM_MODEL is set). It's slow on the Pi,
  so TodoCoach writes the message ahead in the background: when the to-do facts change,
  and every REWRITE_S. The sign speaks a draft only if it was written for the current
  facts less than MAX_AGE_S ago and passed clean_message(); otherwise the template.
"""

import logging
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from dayanpi.focus.todos import TodoList
from dayanpi.focus.tracker import format_spoken_duration
from dayanpi.hardware.llm import OllamaClient
from dayanpi.utils.threads import LoopThread

BEDTIME_ENV = "DAYANPI_BEDTIME"
DEFAULT_BEDTIME = 0  # minutes after midnight: 00:00
NIGHT_END_MINUTES = 5 * 60  # past bedtime lasts until 5 a.m.
DAY_MINUTES = 24 * 60
SPOKEN_MAX = 5  # to-dos read out of each list, then "and N more"

WATCH_INTERVAL_S = 2.0  # how often the writer looks for changed to-dos
REWRITE_S = 240.0  # a new draft every 4 minutes, so one under 5 minutes old is always ready
MAX_AGE_S = 300.0  # the time left in a spoken draft is never older than this
MAX_MESSAGE_CHARS = 400
MAX_SENTENCES = 4
MORE_SENTENCES_FROM = 4  # to-dos (open plus done) that get a fourth sentence, so the model doesn't drop one to fit

SYSTEM_PROMPT = (
    "You write one short message that a small speaker will say out loud to someone working at their desk. "
    "Sound like a friendly, encouraging coach. Use {sentences} short sentences. "
    "Mention the time, the time left until bed, what is left to do and what is already done. "
    "Past bedtime, say it is past bedtime and to wrap up, instead of counting hours. "
    "Use only the facts given: never add, drop or rename a to-do, and never change a time or a number. "
    "No lists, no emojis, no markdown and no quotation marks: plain spoken sentences only."
)
LIST_LINE = re.compile(r"^\s*([-*•]|\d+[.)])\s")
MARKUP = re.compile("[*#`☀-➿\U0001f000-\U0001faff]")
SENTENCE_END = re.compile(r"[.!?](\s|$)")
NUMBER = re.compile(r"\d+")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DoneItem:
    text: str
    seconds: int


@dataclass(frozen=True)
class TodoFacts:
    clock: str  # spoken, like "6 p.m." or "11:50 p.m."
    bedtime: str
    minutes_to_bed: int | None  # None means past bedtime
    open_texts: tuple[str, ...]  # the first SPOKEN_MAX
    open_count: int
    done: tuple[DoneItem, ...]  # the first SPOKEN_MAX, in the order they were finished
    done_count: int

    @property
    def key(self) -> tuple:
        """Everything a draft depends on except the clock, which MAX_AGE_S covers."""
        key = (self.open_texts, self.open_count, self.done, self.done_count, self.minutes_to_bed is None)
        return key


@dataclass(frozen=True)
class Draft:
    key: tuple
    text: str | None  # None: the LLM failed or wrote something unusable
    written_at: float  # when its facts were collected


@dataclass(frozen=True)
class SpokenMessage:
    text: str
    source: str  # "llm" or "template", for the gesture's log line


def read_bedtime(environ: Mapping[str, str] = os.environ) -> int:
    """DAYANPI_BEDTIME as minutes after midnight. Unset or not HH:MM means 00:00 (a bad value warns)."""
    value = environ.get(BEDTIME_ENV, "").strip()
    found = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", value)
    bedtime = int(found.group(1)) * 60 + int(found.group(2)) if found else DEFAULT_BEDTIME
    if value and not found:
        logger.warning("%s=%r isn't HH:MM, using 00:00", BEDTIME_ENV, value)
    return bedtime


def format_spoken_clock(minutes: int) -> str:
    hour, minute = divmod(minutes, 60)
    suffix = "a.m." if hour < 12 else "p.m."
    clock = f"{hour % 12 or 12} {suffix}" if minute == 0 else f"{hour % 12 or 12}:{minute:02d} {suffix}"
    return clock


def count_into_tonight(minutes: int) -> int:
    """Minutes after midnight, with the small hours counted as part of the evening before."""
    counted = minutes + DAY_MINUTES if minutes < NIGHT_END_MINUTES else minutes
    return counted


def collect_facts(snapshot: dict, now: float, bedtime: int) -> TodoFacts:
    """snapshot is TodoList.snapshot(); bedtime is minutes after midnight."""
    moment = datetime.fromtimestamp(now)
    minutes_now = moment.hour * 60 + moment.minute
    left = count_into_tonight(bedtime) - count_into_tonight(minutes_now)
    facts = TodoFacts(
        clock=format_spoken_clock(minutes_now),
        bedtime=format_spoken_clock(bedtime),
        minutes_to_bed=left if left > 0 else None,
        open_texts=tuple(" ".join(item["text"].split()) for item in snapshot["open"][:SPOKEN_MAX]),
        open_count=len(snapshot["open"]),
        done=tuple(DoneItem(" ".join(item["text"].split()), round(item["seconds"])) for item in snapshot["done"][:SPOKEN_MAX]),
        done_count=len(snapshot["done"]),
    )
    return facts


def join_spoken(items: list[str]) -> str:
    """"a", "a and b", "a, b, and c"."""
    joined = ", ".join(items[:-1]) + ", and " + items[-1] if len(items) > 2 else " and ".join(items)
    return joined


def list_with_more(items: list[str], count: int) -> list[str]:
    listed = items + ([f"{count - SPOKEN_MAX} more"] if count > SPOKEN_MAX else [])
    return listed


def describe_time_left(minutes: int) -> str:
    text = "less than 5 minutes" if minutes < 5 else f"about {format_spoken_duration(round(minutes / 5) * 5 * 60)}"
    return text


def describe_done(item: DoneItem) -> str:
    text = f"{item.text} in {format_spoken_duration(item.seconds)}" if item.seconds >= 60 else item.text
    return text


def describe_todos(facts: TodoFacts) -> str:
    """The template, e.g. It's 6 p.m., about 6 hours until bed. You have 3 things to do: finish the report,
    reply to emails, and do laundry. Done today: read chapter 3 in 40 minutes."""
    past_bedtime = facts.minutes_to_bed is None
    things = "thing" if facts.open_count == 1 else "things"
    listed = join_spoken(list_with_more(list(facts.open_texts), facts.open_count))
    parts = [
        f"It's {facts.clock}, past your bedtime." if past_bedtime else f"It's {facts.clock}, {describe_time_left(facts.minutes_to_bed)} until bed.",
        f"You have {facts.open_count} {things} to do: {listed}." if facts.open_count else "Your to-do list is empty.",
        f"Done today: {join_spoken(list_with_more([describe_done(item) for item in facts.done], facts.done_count))}." if facts.done_count else "",
        "Time to wrap up for tonight." if past_bedtime else "",
    ]
    sentence = " ".join(part for part in parts if part)
    return sentence


def build_prompt(facts: TodoFacts) -> str:
    """The facts for the LLM, one per line."""
    more_open = f"; and {facts.open_count - SPOKEN_MAX} more" if facts.open_count > SPOKEN_MAX else ""
    more_done = f"; and {facts.done_count - SPOKEN_MAX} more" if facts.done_count > SPOKEN_MAX else ""
    done = [f"{item.text} (took {format_spoken_duration(item.seconds)})" for item in facts.done]
    lines = [
        f"Time now: {facts.clock}",
        f"Bedtime: {facts.bedtime}, already past" if facts.minutes_to_bed is None else f"Time until bed: {describe_time_left(facts.minutes_to_bed)}",
        f"Open to-dos ({facts.open_count}): " + ("; ".join(facts.open_texts) + more_open if facts.open_texts else "none"),
        f"Done today ({facts.done_count}): " + ("; ".join(done) + more_done if done else "nothing yet"),
    ]
    prompt = "\n".join(lines)
    return prompt


def build_system_prompt(facts: TodoFacts) -> str:
    named = len(facts.open_texts) + len(facts.done)
    system = SYSTEM_PROMPT.format(sentences="3 or 4" if named >= MORE_SENTENCES_FROM else "2 or 3")
    return system


def clean_message(reply: str | None, prompt: str) -> str | None:
    """The reply as one line ready to speak, or None when it's empty, too long, list-like, has markup or emojis,
    or has a number the facts don't (the model making things up)."""
    text = (reply or "").strip().strip('"').strip()
    flat = " ".join(text.split())
    numbers = {int(number) for number in NUMBER.findall(flat)} - {0}  # "6:00" is the 6 p.m. the facts said
    usable = (
        bool(flat)
        and not any(LIST_LINE.match(line) for line in text.splitlines())
        and MARKUP.search(flat) is None
        and len(flat) <= MAX_MESSAGE_CHARS
        and len(SENTENCE_END.findall(flat)) <= MAX_SENTENCES
        and numbers <= {int(number) for number in NUMBER.findall(prompt)}
    )
    cleaned = flat if usable else None
    return cleaned


class TodoCoach(LoopThread):
    """Picks what the peace sign says. With an LLM, start() it to keep a draft written ahead."""

    def __init__(
        self,
        todos: TodoList,
        bedtime: int,
        llm: OllamaClient | None,
        clock=time.time,
        interval_s: float = WATCH_INTERVAL_S,
    ) -> None:
        super().__init__(name="todo-coach", interval_s=interval_s)
        self._todos = todos
        self._bedtime = bedtime
        self._clock = clock
        self.llm = llm
        self.draft: Draft | None = None  # swapped in whole by the writer thread

    def collect(self, now: float) -> TodoFacts:
        facts = collect_facts(self._todos.snapshot(now), now, self._bedtime)
        return facts

    def pick(self, now: float) -> SpokenMessage:
        facts = self.collect(now)
        draft = self.draft
        ready = draft is not None and draft.text is not None and draft.key == facts.key and now - draft.written_at < MAX_AGE_S
        message = SpokenMessage(draft.text, "llm") if ready else SpokenMessage(describe_todos(facts), "template")
        return message

    def tick(self) -> None:
        now = self._clock()
        facts = self.collect(now)
        draft = self.draft
        if draft is None or draft.key != facts.key or now - draft.written_at >= REWRITE_S:
            self.draft = self.write_draft(facts, now)

    def write_draft(self, facts: TodoFacts, now: float) -> Draft:
        prompt = build_prompt(facts)
        reply = self.llm.generate(build_system_prompt(facts), prompt)
        text = clean_message(reply, prompt)
        was_working = self.draft is not None and self.draft.text is not None
        if reply is None and (was_working or self.draft is None):
            logger.warning("peace sign: no LLM message (%s), the template stands in until it's back", self.llm.problem)
        elif reply is not None and text is None:
            logger.info("peace sign: the LLM's message didn't pass, the template stands in: %r", reply[:200])
        elif text is not None and not was_working:
            logger.info("peace sign: LLM messages from %s are ready", self.llm.model)
        draft = Draft(key=facts.key, text=text, written_at=now)
        return draft
