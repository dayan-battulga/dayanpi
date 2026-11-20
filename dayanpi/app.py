import asyncio
import functools
import json
import logging
import math
import os
import re
import threading
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Request, Response, WebSocket, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketClose, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

from typing import Annotated, Literal

from dayanpi.auth import routes as auth_routes
from dayanpi.auth.accounts import SESSION_REFRESH_S, User
from dayanpi.hardware import collector
from dayanpi.focus import days
from dayanpi.focus import worker as focus_worker
from dayanpi.hardware.camera import CameraStream, create_side_stream, create_stream
from dayanpi.focus.browser_camera import BrowserCheck
from dayanpi.focus.camera_source import PI_CAMERAS, SOURCES
from dayanpi.focus.voice_setting import OUTPUTS
from dayanpi.focus.desks import Desk, Desks, move_owner_data
from dayanpi.focus.pictures import PICTURE_MAX_BASE64, read_browser_picture, shrink_frame
from dayanpi.focus.sharing import AT_DESK_STATES, LAMP_COLORS, NUDGE_EVERY_S, build_seat, can_nudge, find_fresh_picture, is_here, share_parts
from dayanpi.focus.tracker import FocusUpdate, find_data_dir, format_day
from dayanpi.focus.coach import BEDTIME_PATTERN, DEFAULT_BEDTIME, CoachWriter, TodoCoach, format_bedtime, parse_bedtime
from dayanpi.focus.talk import TALK_PATH, Listener, TalkError, TalkRoom, read_frame
from dayanpi.focus.todos import PRIORITIES, TEXT_MAX, TODOS_MAX, TodoListFull, hide_priorities
from dayanpi.focus.worker import FocusWorker
from dayanpi.hardware.llm import OllamaClient, read_llm_model
from dayanpi.hardware.voice import ClipShelf, VoiceAnnouncer
from dayanpi.paths import STATIC_DIR
from dayanpi.utils.limits import RefusalNote, TokenBucket
from dayanpi.vision import detector, hands
from dayanpi.vision.gestures import HAND_SIGNS

# uvicorn only configures its own loggers; without this the app's INFO lines
# ("focus tracker running", "voice off, would say ...") never reach journalctl.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

FRAME_BOUNDARY = "frame"
FRAME_TIMEOUT_S = 5.0
MAX_CONSECUTIVE_TIMEOUTS = 3
SNAPSHOT_INTERVAL_S = 1.0
VIDEO_MAX_CONCURRENT = 2
STREAM_MAX_CONCURRENT = 5  # per account
FEED_SESSION_CHECK_S = 1.0  # an open camera feed checks its viewer is still signed in this often
AFTER_MIDNIGHT_S = 5.0  # the day pages get written this long after local midnight
READING_MS_MAX = 60_000  # a browser check that took longer than this is a broken one
# The biggest write body. FastAPI reads a whole body before any max_length runs, and the sign-in is public.
MAX_BODY_BYTES = 64 * 1024
# Every write from a signed-in account, mine too, takes from that account's own allowance. The tracker's reading a
# second and the Mac helper stay far under it.
WRITES_PER_S = 5.0
WRITE_BURST = 20.0

logger = logging.getLogger(__name__)

# Only used to make the owner account when accounts.db has no users (the first start, or after it's deleted).
AUTH_USER = os.environ.get("DAYANPI_USER", "")
AUTH_PASSWORD = os.environ.get("DAYANPI_PASSWORD", "")

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PAGES = {"/login", "/api/health"}
PUBLIC_WRITES = {"/api/login", "/api/join", "/api/logout"}
JOIN_PAGE = re.compile(r"/join/[A-Za-z0-9_-]{1,64}")
CONTENT_LENGTH = re.compile(r"[0-9]{1,9}")
# A join link, in a path or inside a query (a stray "/" on the link turns it into /login?next=%2Fjoin%2F...).
JOIN_LINK = re.compile(r"(/|%2F)join(/|%2F)[^?&\s]*", re.IGNORECASE)
# Members change their own account and their own desk. Every other write is the owner's, so a new write route
# stays owner-only until it's added here as "METHOD /path".
MEMBER_WRITES = re.compile(
    r"PATCH /api/me|POST /api/me/password|POST /api/tokens|DELETE /api/tokens/[0-9]+"
    r"|POST /api/todos|(PATCH|DELETE) /api/todos/[^/]+|POST /api/mac/app|POST /api/mac/tracking"
    r"|POST /api/track/(reading|pause|source)|POST /api/voice(/test)?|POST /api/sharing|POST /api/nudge|POST /api/room/(hide|show)|POST /api/goal|POST /api/notepad"
)
OWNER_READS = {"/api/stats", "/api/invites", "/api/accounts"}
INDEX_PAGE = STATIC_DIR / "index.html"
# The models the tracker pages run in the browser, by file name: nothing else in models/ is served. The page keeps
# them in Cache Storage under this name, so a changed model needs a new file name.
MODEL_FILES = {path.name: path for path in (detector.OBJECT_MODEL_PATH, detector.FACE_MODEL_PATH, hands.PALM_MODEL_PATH, hands.HAND_MODEL_PATH)}
MODEL_CACHE_CONTROL = "private, max-age=31536000, immutable"

sampler = collector.CpuSampler()
stream = create_stream()
side_stream = create_side_stream()
latest_snapshot: dict | None = None  # the Pi's numbers, which only the owner gets
latest_focus: dict[str, dict] = {}  # every desk's focus status by username, made once a second
latest_room: dict | None = None  # everyone's seat as the room sees it (build_room), made once a second
desks = Desks(find_data_dir())
owner_desk: Desk | None = None  # the desk the Pi's cameras and the voice can feed; opened at startup
worker: FocusWorker | None = None
voice = VoiceAnnouncer()
clips = ClipShelf()  # each person's latest peace-sign clip for "This computer"; memory only
LLM_MODEL = read_llm_model()
llm: OllamaClient | None = None  # made at startup when DAYANPI_LLM_MODEL is set; every desk's coach shares it
coach_writer: CoachWriter | None = None  # the one thread that writes every desk's drafts
_coach_lock = threading.Lock()
TEST_LINE = "This is how your peace sign sounds."
VOICE_TEST_EVERY_S = 10.0  # per desk: each test is a Piper run on the Pi

_video_slots = threading.BoundedSemaphore(VIDEO_MAX_CONCURRENT)
_side_video_slots = threading.BoundedSemaphore(VIDEO_MAX_CONCURRENT)
# One pool per account, so a member's open tabs can't use up the owner's.
_stream_slots: defaultdict[int, threading.BoundedSemaphore] = defaultdict(
    lambda: threading.BoundedSemaphore(STREAM_MAX_CONCURRENT)
)


def make_write_allowance() -> TokenBucket:
    return TokenBucket(WRITES_PER_S, WRITE_BURST)


# By user id, which never comes back for another account. In memory, like the sign-in waits.
write_allowances: defaultdict[int, TokenBucket] = defaultdict(make_write_allowance)
write_refusals = RefusalNote()
talk_room = TalkRoom()  # everyone with the Room open, for its voices (focus/talk.py); memory only, never any audio kept
TALK_SESSION_CHECK_S = 2.0  # how soon an open talk socket notices its sign-in is gone
TALK_REPLACED = 4001  # the close code when a newer socket of theirs took over, so the page doesn't try again


class InviteCodeFilter(logging.Filter):
    """uvicorn's access log prints every path with its query, and a join link carries a live invite code."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > 2 and isinstance(args[2], str):
            record.args = args[:2] + (JOIN_LINK.sub(r"\1join\2…", args[2]),) + args[3:]
        return True


PICTURE_PATH = re.compile(r"/api/people/[^/]+/picture")


class QuietAccessFilter(logging.Filter):
    """uvicorn's access log, without what comes every second while the room is open: each seat's picture (its 404 is
    just "not sharing right now"), the tracker's readings and pictures that worked, and every 429, since the limits
    write their own line a minute instead. Sign-ins, joins, every other write and the other errors all stay."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        keep = True
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[4], int):
            method, path, code = args[1], str(args[2]).partition("?")[0], args[4]
            keep = not (
                code == 429
                or (method == "GET" and code in (200, 404) and PICTURE_PATH.fullmatch(path) is not None)
                or (method == "POST" and path in ("/api/track/reading", "/api/track/picture") and 200 <= code < 300)
            )
        return keep


logging.getLogger("uvicorn.access").addFilter(InviteCodeFilter())
logging.getLogger("uvicorn.access").addFilter(QuietAccessFilter())


def stamp_age(event: dict | None, now: float) -> dict | None:
    """The page hides boxes and toasts after a few seconds, so it needs their age, not the Pi's clock."""
    stamped = None if event is None else {**event, "age_s": round(now - event["at"], 1)}
    return stamped


# A desk the Pi's cameras and voice don't reach: everyone's but the owner's.
NO_CAMERA = {
    "enabled": False,
    "side_camera": False,
    "side_camera_running": False,
    "overlay": None,
    "side_overlay": None,
    "gesture": None,
}
# A side camera with no new frame for this long has dropped out, so my tile goes back to the front one.
SIDE_FRESH_S = 3.0


def is_side_camera_running() -> bool:
    """There's a side camera (DAYANPI_CAMERA=both) and it's still sending frames."""
    age = None if side_stream is None else side_stream.frame_age_s()
    running = age is not None and age <= SIDE_FRESH_S
    return running


def build_camera_status(now: float) -> dict:
    """The owner's desk's parts that come off the Pi's cameras and voice."""
    running = worker
    camera = {
        "enabled": running is not None and running.running,
        "side_camera": side_stream is not None,
        "side_camera_running": is_side_camera_running(),  # for Settings → Camera's Front/Side pick
        "overlay": stamp_age(None if running is None else running.last_overlay, now),
        "side_overlay": stamp_age(None if running is None else running.last_side_overlay, now),
        "gesture": stamp_age(None if running is None else running.last_gesture, now),
    }
    return camera


def find_camera_source(desk: Desk) -> str:
    """"pi" or "browser". Only the owner's desk can have the Pi's cameras, and has them until the owner picks a browser."""
    source = "pi" if desk is owner_desk and desk.camera_source.source != "browser" else "browser"
    return source


def find_picture_source(desk: Desk) -> str:
    """Where the seat's picture comes from: "pi" (the front Pi camera) or "browser". Only the owner's desk has a choice;
    until I pick, it's wherever my checks come from."""
    picked = desk.camera_source.picture if desk is owner_desk else "browser"
    source = find_camera_source(desk) if picked is None else picked
    return source


def find_picture_camera(desk: Desk) -> CameraStream:
    """The Pi camera my tile comes from: the side one while I picked it and it's running, otherwise the front, so a side
    camera that's missing or dropped out never leaves my seat blank."""
    camera = side_stream if desk.camera_source.pi_camera == "side" and is_side_camera_running() else stream
    return camera


def find_bedtime(desk: Desk) -> int:
    """Minutes after midnight: what the desk picked in Settings, else 00:00."""
    picked = desk.voice.bedtime
    bedtime = DEFAULT_BEDTIME if picked is None else picked
    return bedtime


def find_voice_output(desk: Desk) -> str:
    """"pi" or "computer". Only my desk can have the Pi's speaker, which is in my room, and has it until I pick my computer."""
    output = "pi" if desk is owner_desk and desk.voice.output != "computer" else "computer"
    return output


def find_coach(desk: Desk) -> TodoCoach:
    """Each desk's own coach, made the first time it's needed: its own to-dos and bedtime, the one LLM."""
    with _coach_lock:
        if desk.coach is None:
            desk.coach = TodoCoach(desk.todos, lambda: find_bedtime(desk), llm)
        coach = desk.coach
    return coach


def describe_spoken(desk: Desk, now: float) -> dict | None:
    """The peace sign's last message for the pill: on the Pi's speaker, whether it's still saying it; for this
    computer, whether a clip is waiting for the page to fetch and play."""
    spoken = desk.last_spoken
    on_pi = find_voice_output(desk) == "pi"
    described = None
    if spoken is not None:
        described = {**stamp_age(spoken, now), "speaking": on_pi and voice.is_saying(spoken["text"]), "clip": not on_pi and clips.has(desk.username, now)}
    return described


def build_desk_status(desk: Desk, now: float) -> dict:
    """One desk's focus status, for the API and the stats stream."""
    source = find_camera_source(desk)
    status = desk.tracker.status(now) | {
        "todos": desk.todos.snapshot(now),
        "mac_tracking": desk.mac_tracking.enabled,
        "camera_source": source,
        "picture_source": find_picture_source(desk),
        "pi_camera": desk.camera_source.pi_camera,  # which Pi camera, when the picture is the Pi's
        "camera_paused": source == "browser" and desk.browser.paused,
        "spoken": describe_spoken(desk, now),
        "bedtime": format_bedtime(find_bedtime(desk)),
        "voice_output": find_voice_output(desk),
        "sharing": desk.sharing.read(),
        "goal_minutes": desk.goal.read()["minutes"],  # your own; never in a seat, so nobody else sees it
        "notepad": desk.notepad.read(),  # which priorities your Room notepad shows; yours alone too
        # Why the Pi's voice can't run is about the Pi, so it's mine to see.
        "voice": {"enabled": voice.enabled, "backend": voice.backend, "problem": voice.problem if desk is owner_desk else None},
    }
    status |= build_camera_status(now) if desk is owner_desk else NO_CAMERA
    if source == "browser":
        # The tracker takes the browser camera's readings whenever they come, and its hand signs are the desk's own.
        status |= {"enabled": True, "gesture": stamp_age(desk.browser.last_gesture, now)}
    return status


def seat_desk(desk: Desk, name: str, status: dict, now: float) -> dict:
    """One desk's seat, through sharing.build_seat: what anyone else may see of it. Being here brings a hidden seat back
    (build_room makes every seat each second, so that's within a second of them coming back)."""
    here = is_here(desk.seen_at, status, now)
    if here:
        desk.seat.update({"hidden": False})  # only writes seat.json when it was hidden
    seat = build_seat(desk.username, name, status, desk.sharing.read(), here, desk.last_nudged, now, desk.picture, desk.seat.read()["hidden"])
    return seat


def keep_picture(desk: Desk, jpeg: bytes | None, state: str, now: float) -> None:
    """The desk's newest picture, only while it shares video and is at the desk; anything else drops the old one too,
    so turning Video off or walking away leaves nothing behind. Memory only."""
    keeps = jpeg is not None and desk.sharing.read()["video"] and state in AT_DESK_STATES
    desk.picture = {"jpeg": jpeg, "at": round(now, 3)} if keeps else None


def take_owner_picture(now: float) -> None:
    """My tile: the picked Pi camera's latest frame (find_picture_camera, front by default), shrunk, once a second, only
    while my picture comes from the Pi, I share video and I'm at the desk. The cameras keep capturing while the browser
    tracks me, so this works then too. The full feeds stay behind the camera lock; this is a separate small copy."""
    desk = owner_desk
    if desk is not None and find_picture_source(desk) == "pi":
        state = desk.tracker.status(now)["state"]
        wants = desk.sharing.read()["video"] and state in AT_DESK_STATES
        frame = find_picture_camera(desk).latest_frame() if wants else None
        keep_picture(desk, None if frame is None else shrink_frame(frame), state, now)


def find_user(username: str) -> User:
    """Raises the same 404 for a name nobody has."""
    user = next((user for user in auth_routes.accounts.list_users() if user.username == username), None)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="nobody by that name")
    return user


def build_history(desk: Desk, sharing: dict[str, bool], joined_at: float, focus: dict, now: float) -> dict:
    """This month's focused minutes per day (today's live, only while they share focus time too) and the total since
    they joined."""
    today = format_day(now)
    live = share_parts(sharing, {"history_today": lambda: {today: days.count_minutes(focus["today"]["working_seconds"])}})
    written = days.read_focus_minutes(desk.days_dir) | live.get("history_today", {})
    joined = format_day(joined_at)
    history = {
        "month": today[:7],
        "today": today,
        "joined_at": joined_at,
        "days": {day: minutes for day, minutes in written.items() if day.startswith(today[:7])},
        "total_minutes": sum(minutes for day, minutes in written.items() if day >= joined),
    }
    return history


def build_their_desk(user: User, now: float) -> dict:
    """Someone's desk as anyone else may see it: their seat and each piece they share, all through sharing.share_parts.
    A piece they don't share is never read from their logs."""
    desk = desks.open(user.username, now)
    focus = build_desk_status(desk, now)
    chart = functools.cache(lambda: days.build_apps_chart(desk.log, now, "today"))
    sharing = desk.sharing.read()
    pieces = share_parts(
        sharing,
        {
            "here_since": lambda: focus["today"]["first_seen"] if is_here(desk.seen_at, focus, now) else None,
            "today": lambda: {key: focus["today"][key] for key in ("working_seconds", "phone_seconds", "pickups")} | {"segments": desk.tracker.segments()},
            "todo_list": lambda: hide_priorities(focus["todos"]),
            "apps": lambda: [{"app": row["app"], "total_seconds": row["total_seconds"]} for row in chart()],
            "app_youtube": lambda: {row["app"]: row["youtube_seconds"] for row in chart() if row.get("youtube_seconds")},
            "sites": lambda: days.build_sites_chart(desk.log, now),
            "history": lambda: build_history(desk, sharing, user.created_at, focus, now),
            "video": lambda: True,
        },
    )
    their = seat_desk(desk, user.display_name, focus, now) | pieces
    return their


def build_room(statuses: dict[str, dict], now: float) -> dict:
    """Everyone's seat, oldest account first, the same for every viewer (their own seat too, so it matches Settings'
    preview). An account whose desk has no status yet (it joined this second) gets its seat next time."""
    seats = [
        seat_desk(desks.open(user.username, now), user.display_name, statuses[user.username], now)
        for user in auth_routes.accounts.list_users()
        if user.username in statuses
    ]
    room = {"seats": seats}
    return room


def find_desk(request: Request) -> Desk:
    """The signed-in person's own desk (a Mac token's account's, for the helper's reports)."""
    desk = desks.open(auth_routes.read_viewer(request).user.username, time.time())
    return desk


def find_owner() -> User:
    owner = next(user for user in auth_routes.accounts.list_users() if user.role == "owner")
    return owner


def find_camera_access(request: Request) -> str:
    """"open" when this request may have the full feeds: the owner's session, and with DAYANPI_TAILSCALE_LOGIN
    set, from the owner's own Tailscale devices. Otherwise why not: "owner_only" or "tailscale_only"."""
    viewer = auth_routes.read_viewer(request)
    if viewer.user.role != "owner" or viewer.session is None:
        access = "owner_only"
    elif auth_routes.TAILSCALE_LOGIN and not auth_routes.is_from_my_devices(request):
        access = "tailscale_only"
    else:
        access = "open"
    return access


def shape_focus(focus: dict, access: str) -> dict:
    """One viewer's copy of the focus status. The boxes come off the camera, so they go wherever the feed can't."""
    shaped = {**focus, "camera_access": access}
    if access != "open":
        shaped["overlay"] = None
        shaped["side_overlay"] = None
    return shaped


def shape_snapshot(request: Request) -> dict | None:
    """One viewer's copy of the latest snapshot: their own desk's focus, plus the Pi's numbers for the owner.
    None until the first one's made (or the first second after someone joins). Everyone gets the room."""
    viewer = auth_routes.read_viewer(request)
    snapshot = latest_snapshot
    focus = latest_focus.get(viewer.user.username)
    shaped = None
    if snapshot is not None and focus is not None:
        mine = {"focus": shape_focus(focus, find_camera_access(request)), "room": latest_room}
        shaped = {**snapshot, **mine} if viewer.user.role == "owner" else mine
    return shaped


def handle_focus_update(desk: Desk, update: FocusUpdate, now: float) -> None:
    """After every check on a desk, from the worker or a browser's camera. Callouts go to the journal, and only mine to
    the speaker, which is in my room."""
    for callout in update.callouts:
        logger.info("focus callout for %s, %s: %s", desk.username, callout.name, callout.text)
        if callout.speak and desk is owner_desk:
            voice.say(callout.text)
    desk.todos.track(update.state == "working", now)


def speak_to(desk: Desk, text: str, now: float, kind: str = "peace") -> None:
    """Says text where the desk's peace sign speaks, and puts it on its pill (desk.last_spoken, never logged). A nudge
    ("nudge") goes the same way, and the page shows it as a toast instead of the pill.

    The Pi's speaker says it with aplay. For this computer, Piper makes a clip that waits in memory for the
    desk's own page (GET /api/voice/clip); a clip for an older message never replaces a newer one's.
    """
    at = round(now, 3)
    desk.last_spoken = {"text": text, "at": at, "kind": kind}
    if find_voice_output(desk) == "pi":
        voice.say(text)
    else:
        clips.drop(desk.username)

        def keep_clip(wav: bytes) -> None:
            if desk.last_spoken is not None and desk.last_spoken["at"] == at:
                clips.put(desk.username, wav, time.time())

        voice.render(text, keep_clip, desk.username)


def say_todos(desk: Desk, now: float) -> dict:
    """The desk's own coach's message, where its peace sign speaks; which kind it was goes on the gesture's log line."""
    message = find_coach(desk).pick(now)
    logger.info("peace sign on %s's desk: the %s message, through %s", desk.username, message.source, find_voice_output(desk))
    speak_to(desk, message.text, now)
    return {"spoken": message.source}


# What each hand sign does when it fires. Its finger rule lives in vision/gestures.py (HAND_SIGNS).
# An action returns extra fields for the sign's gesture line in the focus log.
SIGN_ACTIONS = {"peace": say_todos}


def handle_gesture(desk: Desk, name: str, now: float) -> None:
    """When a hand sign fires on a desk, from the worker or a browser's camera."""
    details = SIGN_ACTIONS[name](desk, now) if name in SIGN_ACTIONS else {}
    desk.tracker.record_gesture(name, now, **details)


def start_focus_worker(desk: Desk) -> FocusWorker | None:
    """The Pi's cameras feed this desk: the owner's."""
    started = None
    scanner = focus_worker.build_scanner()
    if scanner is not None:
        now = time.time()
        restored = desk.tracker.restore(desk.log.read_day(format_day(now)), now)
        if restored:
            logger.info("focus tracker restored %s events from today's log", restored)
        started = FocusWorker(
            stream,
            scanner,
            desk.tracker,
            on_update=lambda update, now: handle_focus_update(desk, update, now),
            on_gesture=lambda name, now: handle_gesture(desk, name, now),
            wait_for_clock_first=True,
            side_stream=side_stream,
            hand_scanner=focus_worker.build_hand_scanner(),
            is_feeding=lambda: find_camera_source(desk) == "pi",
        )
        started.start()
        logger.info("focus tracker running; log in %s", desk.log.directory)
    return started


def tick_browser_desks(now: float) -> None:
    """Every desk on a browser's camera that heard nothing new gets a check without a frame, so a closed laptop is
    "unknown" after 30 s, like a stuck camera. One desk's trouble doesn't stop the others'."""
    for desk in desks.list():
        if find_camera_source(desk) == "browser":
            try:
                update = desk.browser.tick(now)
                if update is not None:
                    handle_focus_update(desk, update, now)
            except Exception:
                logger.exception("browser camera tick failed for %s", desk.username)


async def snapshot_producer() -> None:
    """One owner of the sampler, the browser desks' ticks, and every desk's status once a second; SSE clients only
    read what it made."""
    global latest_snapshot, latest_focus, latest_room
    while True:
        try:
            snapshot = collector.snapshot(sampler)
            now = time.time()
            await asyncio.to_thread(tick_browser_desks, now)
            await asyncio.to_thread(take_owner_picture, now)
            latest_focus = {desk.username: build_desk_status(desk, now) for desk in desks.list()}
            latest_room = build_room(latest_focus, now)
            latest_snapshot = snapshot
        except Exception:
            logger.exception("snapshot producer failed")
        await asyncio.sleep(SNAPSHOT_INTERVAL_S)


def write_day_pages(now: float) -> None:
    """Every desk's missing day pages. One desk's trouble doesn't stop the others'."""
    for desk in desks.list():
        try:
            written = days.write_missing_pages(desk.log, desk.days_dir, now, desk.goal.read()["minutes"])
            if written:
                logger.info("day pages written for %s: %s", desk.username, ", ".join(written))
        except Exception:
            logger.exception("day pages failed for %s", desk.username)


async def day_page_writer() -> None:
    """Writes every desk's missing day pages at startup, then again just after each local midnight.

    It waits for the network clock first, like the focus worker: before that, "today" can
    be a day that's already over.
    """
    await asyncio.to_thread(focus_worker.wait_for_clock)
    while True:
        await asyncio.to_thread(write_day_pages, time.time())
        await asyncio.sleep(days.find_seconds_until_midnight(time.time()) + AFTER_MIDNIGHT_S)


def open_joined_desk(user: User) -> None:
    desks.open(user.username, time.time())


def move_removed_desk(user: User) -> None:
    """The account is gone already; a folder that won't move only costs a line in the journal."""
    try:
        moved = desks.remove(user.username, time.time())
    except OSError:
        logger.exception("couldn't move %s's desk aside", user.username)
    else:
        if moved is not None:
            logger.info("moved %s's desk to %s", user.username, moved)


auth_routes.on_join = open_joined_desk
auth_routes.on_remove = move_removed_desk


def open_desks(now: float) -> Desk:
    """Moves the owner's old data into their folder (once), opens everyone's desk and returns the owner's."""
    owner = find_owner()
    move_owner_data(desks.data_dir, desks.find_folder(owner.username))
    for user in auth_routes.accounts.list_users():
        desks.open(user.username, now)
    opened = desks.open(owner.username, now)
    return opened


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker, owner_desk, llm, coach_writer
    if not AUTH_USER or not AUTH_PASSWORD:
        raise RuntimeError(
            "DAYANPI_USER and DAYANPI_PASSWORD must be set "
            "(e.g. via EnvironmentFile=/etc/dayanpi.env)"
        )
    if auth_routes.accounts.seed_owner(AUTH_USER, AUTH_PASSWORD, time.time()):
        logger.info("made the owner account from DAYANPI_USER and DAYANPI_PASSWORD")
    if auth_routes.TAILSCALE_LOGIN:
        logger.info("camera locked to Tailscale login %s", auth_routes.TAILSCALE_LOGIN)
    else:
        logger.warning("camera not locked to Tailscale, don't turn on Funnel")
    sampler.sample()
    owner_desk = open_desks(time.time())
    llm = None if LLM_MODEL is None else OllamaClient(LLM_MODEL)
    stream.start()
    if side_stream is not None:
        side_stream.start()
    voice.start()
    worker = start_focus_worker(owner_desk)
    if llm is not None:
        coach_writer = CoachWriter(lambda: [find_coach(desk) for desk in desks.list()])
        coach_writer.start()
        logger.info("peace sign: writing everyone's messages ahead with %s through Ollama, one at a time", llm.model)
    else:
        logger.info("peace sign: template messages (DAYANPI_LLM_MODEL isn't set)")
    producer = asyncio.create_task(snapshot_producer(), name="snapshot-producer")
    day_pages = asyncio.create_task(day_page_writer(), name="day-page-writer")
    yield
    for task in (producer, day_pages):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    if worker is not None:
        worker.stop()
        worker = None
    if coach_writer is not None:
        coach_writer.stop()
        coach_writer = None
    for desk in desks.list():
        desk.todos.save(time.time())
    voice.stop()
    stream.stop()
    if side_stream is not None:
        side_stream.stop()


app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class WebSocketGate:
    """Closes every WebSocket handshake but the Room's talk socket, which checks the sign-in itself (talk). The session
    middleware only sees HTTP, so any other one would reach the routes unchecked, and StaticFiles asserts on it: a 500
    and a traceback in the journal per stranger's try."""

    def __init__(self, inner) -> None:
        self.inner = inner

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "websocket" and scope["path"] != TALK_PATH:
            await WebSocketClose(code=1008)(scope, receive, send)
        else:
            await self.inner(scope, receive, send)


app.add_middleware(WebSocketGate)


@app.exception_handler(RequestValidationError)
async def refuse_invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
    """Where and what was wrong, never the value sent."""
    # FastAPI's own 422 repeats each bad value, a password too, and can't encode a lone surrogate or NaN: that
    # 422 turns into a 500 whose traceback writes the value into the journal.
    problems = [{"loc": problem["loc"], "msg": problem["msg"], "type": problem["type"]} for problem in error.errors()]
    response = JSONResponse({"detail": problems}, status_code=422)
    return response


app.include_router(auth_routes.router)


def read_media_type(request: Request) -> str:
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    return media_type


def is_body_small(request: Request) -> bool:
    """uvicorn ends a body at its Content-Length, so a write must send one under the cap. A chunked body has
    none and could run on for as long as the sender likes."""
    length = request.headers.get("content-length", "")
    small = "transfer-encoding" not in request.headers and CONTENT_LENGTH.fullmatch(length) is not None and int(length) <= MAX_BODY_BYTES
    return small


def is_public(method: str, path: str) -> bool:
    """The sign-in and join pages, what they load, and the routes they call."""
    if method in ("GET", "HEAD"):
        is_asset = path.startswith("/assets/") and ".." not in path and "\\" not in path
        public = path in PUBLIC_PAGES or JOIN_PAGE.fullmatch(path) is not None or is_asset
    else:
        public = method == "POST" and path in PUBLIC_WRITES
    return public


def is_member_allowed(method: str, path: str) -> bool:
    allowed = MEMBER_WRITES.fullmatch(f"{method} {path}") is not None if method not in READ_METHODS else path not in OWNER_READS
    return allowed


def refuse_stranger(request: Request, path: str) -> Response:
    """No sign-in: the API, the feeds and a Mac token used anywhere but /api/mac/ get a 401, a page the sign-in page."""
    is_page = request.method in ("GET", "HEAD") and auth_routes.read_bearer(request) is None
    if is_page and not path.startswith(("/api/", "/video")):
        query = request.scope["query_string"].decode("latin-1")
        response = RedirectResponse("/login?next=" + quote(path + (f"?{query}" if query else ""), safe=""), status_code=303)
    else:
        response = JSONResponse({"detail": "sign in first"}, status_code=status.HTTP_401_UNAUTHORIZED)
    return response


def refuse_fast_writes(user: User, wait: float, now: float) -> Response:
    """Past the account's allowance: a 429, and one journal line a minute at most for it, never one per request."""
    if write_refusals.count(user.username, now):
        logger.warning("write limit hit for %s", user.username)
    response = JSONResponse({"detail": "slow down"}, status_code=status.HTTP_429_TOO_MANY_REQUESTS, headers={"Retry-After": str(math.ceil(wait))})
    return response


async def guard_request(request: Request, call_next) -> Response:
    # scope["path"] is what the router matches; request.url.path re-splits it, so a %3F could make the two differ.
    path = request.scope["path"]
    now = time.time()
    if request.method not in READ_METHODS and read_media_type(request) != "application/json":
        # A form or a text/plain post from another site can't send application/json without a CORS preflight.
        response = JSONResponse({"detail": "send JSON"}, status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    elif request.method not in READ_METHODS and not is_body_small(request):
        response = JSONResponse({"detail": "too big"}, status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    elif is_public(request.method, path):
        response = await call_next(request)
    elif (viewer := auth_routes.find_viewer(request, now)) is None:
        response = refuse_stranger(request, path)
    elif viewer.user.role != "owner" and not is_member_allowed(request.method, path):
        response = JSONResponse({"detail": "only the owner can do that"}, status_code=status.HTTP_403_FORBIDDEN)
    elif request.method not in READ_METHODS and (wait := write_allowances[viewer.user.id].take(now)) > 0:
        response = refuse_fast_writes(viewer.user, wait, now)
    else:
        request.state.viewer = viewer
        response = await call_next(request)
        session = viewer.session
        if session is not None and now - session.extended_at > SESSION_REFRESH_S:
            auth_routes.accounts.extend_session(session.token_hash, now)
            auth_routes.set_session_cookie(response, request.cookies[auth_routes.SESSION_COOKIE])
    return response


@app.middleware("http")
async def session_middleware(request: Request, call_next):
    # Covers API routes and StaticFiles — app dependencies don't apply to mounts.
    response = await guard_request(request, call_next)
    # A signed-in browser sends its cookie inside frames too, so another page could frame the dashboard.
    response.headers["X-Frame-Options"] = "DENY"
    # The /join/<code> page must not hand its code to anything it loads or links to.
    response.headers["Referrer-Policy"] = "no-referrer"
    # Without it a browser can keep last week's focus.js against today's index.html after a git pull.
    response.headers.setdefault("Cache-Control", "no-cache")
    # The camera runs from any page, and its models need threads, which only an isolated page gets; a worker in an
    # isolated page only starts if its own script says COEP too. Everything the page loads comes from here, so
    # require-corp blocks nothing, and on an API answer or an asset the headers do nothing.
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    return response


def is_same_origin(websocket: WebSocket) -> bool:
    """The page that opened the socket is on this site. A browser always says where a WebSocket comes from, and the
    SameSite cookie aside, nothing else would stop another site's page from opening one with a visitor's sign-in."""
    host = websocket.headers.get("host", "")
    same = host != "" and urlsplit(websocket.headers.get("origin", "")).netloc == host
    return same


async def close_quietly(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except RuntimeError:
        pass  # the other side closed it first


async def pass_frames_on(websocket: WebSocket, listener: Listener, token: str) -> None:
    """Sends the listener the frames for them until a newer socket of theirs takes over or their sign-in is gone
    (signed out, a password change, the account removed), checked every TALK_SESSION_CHECK_S, then closes it."""
    signed_in = True
    checked_at = time.monotonic()
    try:
        while signed_in and not listener.replaced:
            try:
                await websocket.send_bytes(await asyncio.wait_for(listener.queue.get(), TALK_SESSION_CHECK_S))
            except TimeoutError:
                pass
            if time.monotonic() - checked_at >= TALK_SESSION_CHECK_S:
                signed_in = auth_routes.accounts.find_session(token, time.time()) is not None
                checked_at = time.monotonic()
        await close_quietly(websocket, TALK_REPLACED if signed_in else status.WS_1008_POLICY_VIOLATION)
    except (WebSocketDisconnect, RuntimeError):
        pass  # it closed under us; take_talk is ending too


async def take_talk(websocket: WebSocket, username: str, token: str) -> None:
    """Routes the talker's frames (talk_room.route) while pass_frames_on sends them theirs, until either side closes.
    Anything that isn't a talk frame, text included, closes the socket."""
    listener = talk_room.join(username)
    sending = asyncio.create_task(pass_frames_on(websocket, listener, token))
    try:
        while not sending.done():
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            frame = read_frame(message.get("bytes") or b"")
            talk_room.route(listener, frame, lambda name: desks.open(name, time.time()).sharing.read(), time.time())
    except TalkError:
        await close_quietly(websocket, status.WS_1007_INVALID_FRAME_PAYLOAD_DATA)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        talk_room.leave(listener)
        sending.cancel()


@app.websocket(TALK_PATH)
async def talk(websocket: WebSocket):
    """The Room's voices (focus/talk.py). The session middleware never sees a WebSocket, so this does its check before
    accepting: a page on this site with a live session cookie (a Mac token never counts). Anyone else's handshake is
    refused."""
    viewer = auth_routes.find_viewer(websocket, time.time()) if is_same_origin(websocket) else None
    if viewer is None or viewer.session is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    else:
        await websocket.accept()
        await take_talk(websocket, viewer.user.username, websocket.cookies[auth_routes.SESSION_COOKIE])


def frame_generator(camera: CameraStream, token: str) -> Iterator[bytes]:
    """Ends once the viewer's session is gone, like the stats stream: signed out, or ended by a password change."""
    last_id = -1
    consecutive_timeouts = 0
    checked_at = time.monotonic()

    while True:
        if time.monotonic() - checked_at >= FEED_SESSION_CHECK_S:
            if auth_routes.accounts.find_session(token, time.time()) is None:
                return
            checked_at = time.monotonic()
        result = camera.frame_after(last_id, timeout=FRAME_TIMEOUT_S)
        if result is None:
            consecutive_timeouts += 1
            if consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                return
            continue

        consecutive_timeouts = 0
        jpeg, last_id = result
        yield (
            f"--{FRAME_BOUNDARY}\r\n"
            f"Content-Type: image/jpeg\r\n"
            f"Content-Length: {len(jpeg)}\r\n"
            f"\r\n"
        ).encode("ascii") + jpeg + b"\r\n"


async def event_stream(request: Request) -> AsyncIterator[bytes]:
    """Each viewer gets their own desk's copy of the latest snapshot, and the stream ends once their session is gone."""
    token = request.cookies.get(auth_routes.SESSION_COOKIE, "")
    try:
        yield b"retry: 5000\n\n"
        while True:
            if await request.is_disconnected():
                break
            # Signed out, or the account removed: no more live data from this second on.
            if auth_routes.accounts.find_session(token, time.time()) is None:
                break

            # An open stream is the site open, which counts as here in the room.
            find_desk(request).seen_at = time.time()
            shaped = shape_snapshot(request)
            if shaped is not None:
                yield f"data: {json.dumps(shaped)}\n\n".encode("utf-8")
            else:
                yield b": ping\n\n"

            await asyncio.sleep(SNAPSHOT_INTERVAL_S)
    finally:
        logger.info("SSE client disconnected")


@app.get("/api/stats")
def stats(request: Request):
    """Owner only (OWNER_READS)."""
    return shape_snapshot(request) or {}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/focus")
def focus_now(request: Request):
    desk = find_desk(request)
    status = shape_focus(build_desk_status(desk, time.time()), find_camera_access(request))
    status["segments"] = desk.tracker.segments()
    return status


TodoText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TEXT_MAX)]


class TodoNew(BaseModel):
    text: TodoText


class TodoChange(BaseModel):
    text: TodoText | None = None
    done: bool | None = None
    current: bool | None = None
    priority: Literal[PRIORITIES] | None = None


def build_today_page(desk: Desk, now: float) -> str:
    today = format_day(now)
    page = days.build_day_page(desk.log.read_day(today), today, desk.goal.read()["minutes"])
    return page


@app.get("/api/days")
def month_days(request: Request, month: Annotated[str, Query(pattern=days.MONTH_PATTERN)]):
    """A month's numbers for the calendar, one entry per day with a page. Today's comes live from the log."""
    desk = find_desk(request)
    now = time.time()
    today = format_day(now)
    found = days.read_month(desk.days_dir, month)
    if today.startswith(month + "-"):
        found[today] = days.read_page_totals(build_today_page(desk, now))
    return {"month": month, "today": today, "days": found}


@app.get("/api/apps")
def list_apps(request: Request, range: Annotated[Literal["today", "week"], Query()] = "today"):
    """Time per Mac app for the Apps card, biggest first: the top 8, then the rest as "Other apps"."""
    apps = days.build_apps_chart(find_desk(request).log, time.time(), range)
    return {"range": range, "apps": apps}


@app.get("/api/days/{day}")
def day_page(request: Request, day: Annotated[str, PathParam(pattern=days.DAY_PATTERN)]):
    """One day's page as markdown. The pattern keeps the name to digits and dashes, so it can only be a file in the desk's days/."""
    desk = find_desk(request)
    now = time.time()
    today = format_day(now)
    path = desk.days_dir / f"{day}.md"
    if day == today:
        page = build_today_page(desk, now)
    elif path.is_file():
        page = path.read_text(encoding="utf-8")
    else:
        raise HTTPException(status_code=404, detail="no page for that day")
    return {"day": day, "today": day == today, "markdown": page, "studied_with": list_studied_with(desk, day, now)}


def list_studied_with(mine: Desk, day: str, now: float) -> list[dict]:
    """The day page's Studied with: everyone you were focused at the same time as for STUDIED_WITH_MIN_S or more that
    day, most first, worked out from both focus logs. Only people who share focus time and history (sharing.share_parts)."""
    my_lines = mine.log.read_day(day)
    found = []
    for user in auth_routes.accounts.list_users():
        if user.username != mine.username:
            desk = desks.open(user.username, now)
            sharing = desk.sharing.read()
            overlap = share_parts(sharing, {"studied_with": lambda: days.count_overlap_seconds(my_lines, desk.log.read_day(day), day)}).get("studied_with", 0.0)
            if overlap >= days.STUDIED_WITH_MIN_S:
                seat = share_parts(sharing, {"username": lambda: user.username, "name": lambda: user.display_name, "lamp": lambda: sharing["lamp"]})
                found.append(seat | {"minutes": days.count_minutes(overlap)})
    studied_with = sorted(found, key=lambda person: -person["minutes"])
    return studied_with


@app.get("/api/todos")
def list_todos(request: Request):
    return find_desk(request).todos.snapshot(time.time())


@app.post("/api/todos")
def add_todo(request: Request, new: TodoNew):
    todos = find_desk(request).todos
    now = time.time()
    try:
        item = todos.add(new.text, now)
    except TodoListFull:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"that's {TODOS_MAX} to-dos already; finish or delete some first") from None
    return {"status": "ok", "item": item, "todos": todos.snapshot(now)}


@app.patch("/api/todos/{item_id}")
def change_todo(request: Request, item_id: str, change: TodoChange):
    todos = find_desk(request).todos
    now = time.time()
    if not todos.change(item_id, now, text=change.text, done=change.done, current=change.current, priority=change.priority):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such to-do")
    return {"status": "ok", "todos": todos.snapshot(now)}


@app.delete("/api/todos/{item_id}")
def delete_todo(request: Request, item_id: str):
    todos = find_desk(request).todos
    now = time.time()
    if not todos.delete(item_id, now):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such to-do")
    return {"status": "ok", "todos": todos.snapshot(now)}


# A plain host name like youtube.com: lowercase labels of letters, digits and inner hyphens. The Mac helper
# makes the same check, so a full URL, a path or a page title can't get through either end.
SITE_PATTERN = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
SITE_MAX = 253


class AppReport(BaseModel):
    app: str = Field(min_length=1, max_length=100)
    site: Annotated[str, StringConstraints(max_length=SITE_MAX, pattern=SITE_PATTERN)] | None = None


class MacTrackingChange(BaseModel):
    enabled: StrictBool


@app.post("/api/mac/app")
def mac_app(request: Request, report: AppReport):
    """The token's own desk. While its Mac tracking is off the tracker drops the report; "enabled" tells the helper to stop asking."""
    desk = find_desk(request)
    changed = desk.tracker.record_app(report.app.strip(), time.time(), site=report.site)
    return {"status": "ok", "changed": changed, "enabled": desk.mac_tracking.enabled}


@app.get("/api/mac/tracking")
def get_mac_tracking(request: Request):
    return {"enabled": find_desk(request).mac_tracking.enabled}


@app.post("/api/mac/tracking")
def set_mac_tracking(request: Request, change: MacTrackingChange):
    desk = find_desk(request)
    if desk.mac_tracking.set(change.enabled):
        desk.tracker.set_mac_tracking(change.enabled, time.time())
    return {"enabled": desk.mac_tracking.enabled}


class TrackReading(BaseModel):
    """One check from the browser's camera: what the tracker reads from it and how long it took, plus the seat's
    picture when the last answer asked for one. Nothing else: an extra field is a 422."""

    model_config = ConfigDict(extra="forbid")

    person: float = Field(ge=0, le=1)
    phone: float = Field(ge=0, le=1)  # the best phone near a hand
    sign: Literal[tuple(HAND_SIGNS)] | None = None  # the hand sign this check saw; the Pi does the hold
    elapsed_ms: float = Field(ge=0, le=READING_MS_MAX)
    # The seat's small JPEG (base64), only when the last reply said send_picture. Never part of the check itself.
    picture: Annotated[str, StringConstraints(max_length=PICTURE_MAX_BASE64)] | None = None


class TrackSource(BaseModel):
    """Settings → Camera: where the checks come from, and (the owner's only) where the seat's picture comes from and from
    which Pi camera."""

    model_config = ConfigDict(extra="forbid")

    source: Literal[SOURCES] | None = None
    picture: Literal[SOURCES] | None = None
    pi_camera: Literal[PI_CAMERAS] | None = None


class TrackPicture(BaseModel):
    """The seat's picture on its own, for a desk the Pi tracks but whose picture is this browser's: base64 JPEG, or
    null to only ask whether to send one."""

    model_config = ConfigDict(extra="forbid")

    picture: Annotated[str, StringConstraints(max_length=PICTURE_MAX_BASE64)] | None = None


def require_browser_source(desk: Desk) -> None:
    if find_camera_source(desk) != "browser":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="this desk uses the Pi's cameras")


def wants_browser_picture(desk: Desk, state: str) -> bool:
    """Whether the browser should send the seat's picture: it's the desk's picture source, video is shared and the desk
    is at the desk."""
    wants = find_picture_source(desk) == "browser" and desk.sharing.read()["video"] and state in AT_DESK_STATES
    return wants


def describe_tracking(desk: Desk, now: float) -> dict:
    """The answer to the browser's camera, from the Pi's own clock: the desk's state, the peace sign's last message, and
    whether to send the seat's picture with the next reading."""
    focus = desk.tracker.status(now)
    described = {
        "state": focus["state"],
        "seconds_in_state": focus["seconds_in_state"],
        "paused": desk.browser.paused,
        "spoken": describe_spoken(desk, now),
        "send_picture": wants_browser_picture(desk, focus["state"]),
    }
    return described


@app.post("/api/track/reading")
def track_reading(request: Request, reading: TrackReading):
    """A browser's check, for the sender's own desk, about one a second (faster is a 429)."""
    desk = find_desk(request)
    require_browser_source(desk)
    now = time.time()
    taken = desk.browser.take(BrowserCheck(reading.person, reading.phone, reading.sign, reading.elapsed_ms), now)
    if taken is None:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="one reading a second")
    handle_focus_update(desk, taken.update, now)
    if find_picture_source(desk) == "browser":  # otherwise the Pi's front camera makes it
        keep_picture(desk, None if reading.picture is None else read_browser_picture(reading.picture), taken.update.state, now)
    if taken.gesture is not None:
        logger.info("gesture on %s's desk: %s", desk.username, taken.gesture)
        handle_gesture(desk, taken.gesture, now)
    return describe_tracking(desk, now)


@app.post("/api/track/pause")
def pause_tracking(request: Request):
    """The camera's Turn off: the desk says paused, not broken, until its next reading."""
    desk = find_desk(request)
    require_browser_source(desk)
    now = time.time()
    handle_focus_update(desk, desk.browser.pause(now), now)
    desk.picture = None
    return describe_tracking(desk, now)


@app.post("/api/track/picture")
def track_picture(request: Request, sent: TrackPicture):
    """The seat's picture from a browser that only sends pictures, about one a second: my desk, while the Pi tracks it
    and the picture is the browser's. Owner only (not in MEMBER_WRITES), since a member's reading carries theirs."""
    desk = find_desk(request)
    if find_picture_source(desk) != "browser":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="this desk's picture comes from the Pi's camera")
    now = time.time()
    state = desk.tracker.status(now)["state"]
    keep_picture(desk, None if sent.picture is None else read_browser_picture(sent.picture), state, now)
    return {"state": state, "send_picture": wants_browser_picture(desk, state)}


@app.post("/api/track/source")
def set_camera_source(request: Request, change: TrackSource):
    """Settings → Camera. Only the owner's desk can have the Pi's cameras, or pick where its picture comes from."""
    desk = find_desk(request)
    owner = auth_routes.read_viewer(request).user.role == "owner"
    if change.source == "pi" and not owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="only the owner's desk has the Pi's cameras")
    if (change.picture is not None or change.pi_camera is not None) and not owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="your picture is always your browser's")
    if desk.camera_source.update(change.model_dump(exclude_none=True)):
        logger.info(
            "%s's desk: checks from the %s, picture from the %s (%s camera)",
            desk.username,
            find_camera_source(desk),
            find_picture_source(desk),
            desk.camera_source.pi_camera,
        )
    return {"source": find_camera_source(desk), "picture": find_picture_source(desk), "pi_camera": desk.camera_source.pi_camera}


class SharingChange(BaseModel):
    """Settings → Share with the room: the switches to change, and the lamp color. Status is always on, so it isn't one."""

    model_config = ConfigDict(extra="forbid")

    focus: StrictBool | None = None
    todos: StrictBool | None = None
    history: StrictBool | None = None
    apps: StrictBool | None = None
    sites: StrictBool | None = None
    video: StrictBool | None = None
    nudges: StrictBool | None = None
    hear_room: StrictBool | None = None
    direct_talk: StrictBool | None = None
    lamp: Literal[LAMP_COLORS] | None = None  # only the presets


@app.post("/api/sharing")
def set_sharing(request: Request, change: SharingChange):
    """Your own desk's switches. The reply has your seat exactly as the room now gets it, for Settings' preview."""
    desk = find_desk(request)
    desk.sharing.update(change.model_dump(exclude_none=True))
    sharing = desk.sharing.read()
    if not sharing["video"]:
        desk.picture = None  # hidden means gone from the Pi this moment, not in 3 seconds
    now = time.time()
    seat = seat_desk(desk, auth_routes.read_viewer(request).user.display_name, build_desk_status(desk, now), now)
    return {"sharing": sharing, "seat": seat}


@app.get("/api/people/{username}")
def their_desk(username: str):
    """Someone's desk (TheirDesk), the quick peek's too: only what they share. Your own works, as the room sees it."""
    return build_their_desk(find_user(username), time.time())


@app.get("/api/people/{username}/picture")
def their_picture(username: str):
    """Someone's seat picture as a JPEG, through sharing.share_parts: only while they share video, are at the desk and
    the picture is under 3 s old; otherwise the same 404 as nobody. Signed-in room members only, like every /api/ route."""
    user = find_user(username)
    now = time.time()
    desk = desks.open(user.username, now)
    focus = desk.tracker.status(now)
    shared = share_parts(desk.sharing.read(), {"picture": lambda: find_fresh_picture(desk.picture, focus, is_here(desk.seen_at, focus, now), now)})
    fresh = shared.get("picture")
    if fresh is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no picture")
    return Response(fresh["jpeg"], media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


class PersonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)


def nudge_line(sender: str) -> str:
    return f"{sender} says put the phone down"


@app.post("/api/nudge")
def nudge(request: Request, asked: PersonRequest):
    """Nudges someone who's been on their phone NUDGE_AFTER_S: their speaker says so, where their peace sign speaks (the
    Pi's for me, their own computer for anyone else). At most one per person every NUDGE_EVERY_S, from anyone."""
    sender = auth_routes.read_viewer(request).user
    target = find_user(asked.username)
    if target.id == sender.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="that's you")
    now = time.time()
    desk = desks.open(target.username, now)
    seat = seat_desk(desk, target.display_name, build_desk_status(desk, now), now)
    wait = 0.0 if seat.get("nudge") is None else seat["nudge"]["wait_s"]
    if wait > 0:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="nudged a few minutes ago", headers={"Retry-After": str(int(wait) + 1)})
    if not can_nudge(seat):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="they can't be nudged right now")
    desk.last_nudged = {"by": sender.username, "at": round(now, 3)}
    logger.info("%s nudged %s, through %s", sender.username, target.username, find_voice_output(desk))
    speak_to(desk, nudge_line(sender.display_name), now, kind="nudge")
    return {"status": "ok", "wait_s": NUDGE_EVERY_S}


def set_seat_hidden(request: Request, asked: PersonRequest, hidden: bool) -> dict:
    """Tidies an offline seat out of the room for everyone, or puts it back. Their account, desk and data stay as they
    are, and seat_desk brings the seat back by itself once they're here."""
    viewer = auth_routes.read_viewer(request).user
    target = find_user(asked.username)
    if target.id == viewer.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="that's you")
    now = time.time()
    desk = desks.open(target.username, now)
    if hidden and is_here(desk.seen_at, desk.tracker.status(now), now):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="they're here right now")
    desk.seat.update({"hidden": hidden})
    logger.info("%s %s %s's seat", viewer.username, "hid" if hidden else "showed", target.username)
    return {"username": target.username, "hidden": hidden}


@app.post("/api/room/hide")
def hide_seat(request: Request, asked: PersonRequest):
    return set_seat_hidden(request, asked, True)


@app.post("/api/room/show")
def show_seat(request: Request, asked: PersonRequest):
    """The toast's Undo."""
    return set_seat_hidden(request, asked, False)


class NotepadChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high: StrictBool | None = None
    medium: StrictBool | None = None
    low: StrictBool | None = None
    none: StrictBool | None = None


@app.post("/api/notepad")
def set_notepad(request: Request, change: NotepadChange):
    """Settings → To-dos: which priorities the Room's notepad shows, for your own desk."""
    notepad = find_desk(request).notepad
    notepad.update(change.model_dump(exclude_none=True))
    return notepad.read()


class GoalChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minutes: Annotated[int, Field(strict=True, ge=days.GOAL_MIN_MINUTES, le=days.GOAL_MAX_MINUTES, multiple_of=days.GOAL_STEP_MINUTES)] | None


@app.post("/api/goal")
def set_goal(request: Request, change: GoalChange):
    """Settings → Profile's Daily focus goal, for your own desk: null is off."""
    goal = find_desk(request).goal
    goal.update({"minutes": change.minutes})
    return goal.read()


class VoiceChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bedtime: Annotated[str, StringConstraints(pattern=rf"^{BEDTIME_PATTERN}$")] | None = None  # "HH:MM"
    output: Literal[OUTPUTS] | None = None


@app.post("/api/voice")
def set_voice(request: Request, change: VoiceChange):
    """Settings → Voice and bedtime, for your own desk. Only my desk can have the Pi's speaker."""
    desk = find_desk(request)
    if change.output == "pi" and auth_routes.read_viewer(request).user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="only the owner's desk has the Pi's speaker")
    desk.voice.set(bedtime=None if change.bedtime is None else parse_bedtime(change.bedtime), output=change.output)
    return {"bedtime": format_bedtime(find_bedtime(desk)), "output": find_voice_output(desk)}


@app.post("/api/voice/test")
def test_voice(request: Request):
    """Settings' Test the voice: a short line wherever your peace sign speaks, with its pill. Once every
    VOICE_TEST_EVERY_S per desk; sooner is a 429 that says how long to wait."""
    desk = find_desk(request)
    now = time.time()
    wait = 0.0 if desk.voice_tested_at is None else desk.voice_tested_at + VOICE_TEST_EVERY_S - now
    if wait > 0:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="one test every 10 s", headers={"Retry-After": str(math.ceil(wait))})
    desk.voice_tested_at = now
    speak_to(desk, TEST_LINE, now)
    return {"output": find_voice_output(desk), "voice": voice.enabled}


@app.get("/api/voice/clip")
def voice_clip(request: Request):
    """Your own latest peace-sign clip as a WAV, once: it leaves the Pi's memory when it's fetched, or a minute after
    it was made, whichever comes first."""
    wav = clips.take(auth_routes.read_viewer(request).user.username, time.time())
    if wav is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no clip")
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


class SlotResponse(StreamingResponse):
    """A stream on a capped route, which gives its slot back the moment it ends, however it ends.

    A finally inside the generator can't do this. When a viewer hangs up the generator just stops
    being read, so its finally waits for the garbage collector, and until then the next viewer
    gets a 503. If they hang up before it starts, the finally never runs at all.
    """

    def __init__(self, content, slots: threading.BoundedSemaphore, **options) -> None:
        super().__init__(content, **options)
        self._slots = slots

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._slots.release()


@app.get("/api/stream")
async def api_stream(request: Request):
    slots = _stream_slots[auth_routes.read_viewer(request).user.id]
    if not slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many stream connections",
        )

    return SlotResponse(
        event_stream(request),
        slots,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def stream_video(camera: CameraStream, slots: threading.BoundedSemaphore, request: Request) -> StreamingResponse:
    if not slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many video connections",
        )

    response = SlotResponse(
        frame_generator(camera, request.cookies.get(auth_routes.SESSION_COOKIE, "")),
        slots,
        media_type=f"multipart/x-mixed-replace; boundary={FRAME_BOUNDARY}",
    )
    return response


def require_camera(request: Request) -> None:
    """The same plain 404 as a route that doesn't exist, for a member, a stranger's header or none at all."""
    if find_camera_access(request) != "open":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@app.get("/video")
def video(request: Request):
    require_camera(request)
    return stream_video(stream, _video_slots, request)


@app.get("/video/side")
def side_video(request: Request):
    require_camera(request)
    if side_stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No side camera")
    return stream_video(side_stream, _side_video_slots, request)


@app.get("/api/models/{name}")
def model_file(name: str):
    """One of the four ONNX files, for the tracker pages. Signed in only, like every /api/ route."""
    path = MODEL_FILES.get(name)
    if path is None or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type="application/octet-stream", headers={"Cache-Control": MODEL_CACHE_CONTROL})


@app.get("/login")
@app.get("/join/{code}")
@app.get("/settings")
@app.get("/me")
@app.get("/pi")
@app.get("/track")
@app.get("/track/test")
@app.get("/sign")
@app.get("/people/{username}")
def page():
    """The page's own routes; the page picks what to show from the address. "/" comes from the static mount."""
    return FileResponse(INDEX_PAGE)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
