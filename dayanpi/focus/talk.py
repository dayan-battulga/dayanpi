"""Talking in the room: the Pi passes each person's Opus frames on to whoever they're for, and nothing else.

Every browser in the Room keeps one WebSocket open (app.py's /api/talk). A talker's frames come in as
[target length][target username, empty for everyone][one Opus frame] and go out to each listener as
[kind: TO_EVERYONE or TO_YOU][sender length][sender username][the same frame]. Who hears what is each listener's own
Settings → Sharing: "hear_room" off and the Pi sends them nothing, "direct_talk" off and frames meant for them alone
are dropped. The Pi never decodes, keeps, logs or writes audio anywhere: a frame lives in memory for as long as it takes
to hand it on, in a short queue per listener.

With smooth video on (focus/smooth_video.py) the same socket carries the browsers' WebRTC signaling as text,
{"to": username, "signal": {...}} in and {"from": username, "signal": {...}} out, passed along unread between the
people connected: the offers, answers and ICE candidates that let two browsers send each other their camera directly.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from dayanpi.utils.limits import RefusalNote, TokenBucket

TALK_PATH = "/api/talk"
TARGET_MAX_BYTES = 32  # accounts.USERNAME_PATTERN: at most 32 plain characters
# An Opus frame at 24 kbps and 20 ms is about 60 bytes, and loud speech stays well under 200; anything this big isn't one.
FRAME_MAX_BYTES = 400
FRAMES_PER_S = 50.0  # one every 20 ms
FRAME_BURST = 100.0  # two seconds' worth, for a talker whose connection stalled and then caught up
LISTEN_QUEUE = 25  # frames waiting for one slow listener (half a second); past that, theirs are dropped
TO_EVERYONE = 0
TO_YOU = 1
SIGNAL_MAX_CHARS = 16_384  # an offer with its video codecs is a few KB; anything this long isn't one
SIGNALS_PER_S = 20.0  # a connection's setup is an offer, an answer and a few dozen candidates
SIGNAL_BURST = 100.0

logger = logging.getLogger(__name__)


class TalkError(Exception):
    """A message that isn't a talk frame: the socket closes."""


@dataclass
class TalkFrame:
    target: str | None  # None is everyone
    opus: bytes


def read_frame(message: bytes) -> TalkFrame:
    """One talker's message, or TalkError for anything else: empty, a target too long or cut short, not UTF-8, no
    frame, or a frame over FRAME_MAX_BYTES."""
    length = message[0] if message else -1
    opus = message[1 + length :] if length >= 0 else b""
    if length < 0 or length > TARGET_MAX_BYTES or len(message) < 1 + length or not opus or len(opus) > FRAME_MAX_BYTES:
        raise TalkError("not a talk frame")
    try:
        target = message[1 : 1 + length].decode("utf-8")
    except UnicodeDecodeError:
        raise TalkError("target isn't text") from None
    frame = TalkFrame(target or None, opus)
    return frame


@dataclass
class TalkSignal:
    to: str
    signal: dict  # passed on as it came; the Pi never reads it


def read_signal(text: str) -> TalkSignal:
    """One browser's signaling message, or TalkError for anything else: too long, not JSON, not {"to": a username
    of at most TARGET_MAX_BYTES, "signal": an object}."""
    try:
        data = json.loads(text) if len(text) <= SIGNAL_MAX_CHARS else None
    except ValueError:
        data = None
    to = data.get("to") if isinstance(data, dict) else None
    signal = data.get("signal") if isinstance(data, dict) else None
    if not isinstance(to, str) or not 0 < len(to.encode("utf-8")) <= TARGET_MAX_BYTES or not isinstance(signal, dict):
        raise TalkError("not a signal")
    read = TalkSignal(to, signal)
    return read


def pack_frame(kind: int, sender: str, opus: bytes) -> bytes:
    name = sender.encode("utf-8")
    packed = bytes([kind, len(name)]) + name + opus
    return packed


@dataclass(eq=False)
class Listener:
    """One person's open socket: what's waiting to go out to them, and how fast they may talk."""

    username: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=LISTEN_QUEUE))
    allowance: TokenBucket = field(default_factory=lambda: TokenBucket(FRAMES_PER_S, FRAME_BURST))
    signal_allowance: TokenBucket = field(default_factory=lambda: TokenBucket(SIGNALS_PER_S, SIGNAL_BURST))
    replaced: bool = False  # a newer socket of theirs took over: this one closes and its page doesn't try again

    def offer(self, message: bytes | str) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            pass  # they can't keep up; a gap beats a growing delay


class TalkRoom:
    """Everyone with the Room open, by username: one socket each, the newest one."""

    def __init__(self) -> None:
        self._listeners: dict[str, Listener] = {}
        self._refusals = RefusalNote()

    def join(self, username: str) -> Listener:
        joined = Listener(username)
        old = self._listeners.get(username)
        if old is not None:
            old.replaced = True
        self._listeners[username] = joined
        return joined

    def leave(self, listener: Listener) -> None:
        if self._listeners.get(listener.username) is listener:
            del self._listeners[listener.username]

    def route(self, talker: Listener, frame: TalkFrame, sharing_of: Callable[[str], dict], now: float) -> int:
        """Hands the frame to everyone it's for and returns how many: everyone here but the talker who hears the room,
        or the one person, if they hear the room and take direct talk. Past the talker's allowance it goes nowhere."""
        recipients: list[Listener] = []
        if talker.allowance.take(now) > 0:
            if count := self._refusals.count(talker.username, now):
                logger.warning("talk limit hit for %s (%s frames dropped)", talker.username, count)
        elif frame.target is None:
            recipients = [listener for name, listener in self._listeners.items() if name != talker.username and sharing_of(name)["hear_room"]]
        elif frame.target != talker.username and (listener := self._listeners.get(frame.target)) is not None:
            sharing = sharing_of(frame.target)
            recipients = [listener] if sharing["hear_room"] and sharing["direct_talk"] else []
        message = pack_frame(TO_EVERYONE if frame.target is None else TO_YOU, talker.username, frame.opus)
        for listener in recipients:
            listener.offer(message)
        return len(recipients)

    def relay(self, talker: Listener, signal: TalkSignal, now: float) -> bool:
        """Passes a signaling message to the one person it's for, if they're connected and it isn't the talker, within
        the talker's signal allowance. Returns whether it went."""
        listener = self._listeners.get(signal.to) if signal.to != talker.username else None
        sent = listener is not None and talker.signal_allowance.take(now) == 0
        if sent:
            listener.offer(json.dumps({"from": talker.username, "signal": signal.signal}))
        return sent
