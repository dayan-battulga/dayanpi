"""The account routes: signing in and out, joining from an invite, your own name, password and Mac
helper tokens, and the owner's invites and accounts.

app.py's middleware decides who gets this far (the sign-in and the roles); these handlers only
check what's yours. The store and the lockout live here, and the middleware reads them from here.
"""

import asyncio
import logging
import math
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Annotated, TypeVar

from fastapi import APIRouter, HTTPException, Path as PathParam, Request, Response, status
from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from dayanpi.auth.accounts import (
    PASSWORD_MAX,
    PASSWORD_MIN,
    SESSION_TTL_S,
    TOKEN_NAME_MAX,
    TOKENS_MAX,
    AccountStore,
    InviteNotFound,
    LoginLockout,
    RoomFull,
    Session,
    TooManyTokens,
    User,
    UsernameTaken,
    check_display_name,
    check_sign_in,
    check_username,
    find_accounts_path,
    normalize_username,
)
from dayanpi.utils.limits import RefusalNote, TokenBucket

SESSION_COOKIE = "__Host-dayanpi_session"
MAC_PREFIX = "/api/mac/"
WRONG_LOGIN = "wrong username or password"
TOO_MANY_TRIES = "too many tries, wait a bit"
ROOM_FULL = "the room is full"
# Tailscale Serve sets Tailscale-User-Login on requests from your own tailnet devices and drops any copy a
# client sends; Funnel (the public internet) never has it. The camera lock and the sign-in both go by it.
TAILSCALE_LOGIN = os.environ.get("DAYANPI_TAILSCALE_LOGIN", "").strip()
TAILSCALE_HEADER = "Tailscale-User-Login"

accounts = AccountStore(find_accounts_path())
# app.py hangs each person's desk on these: opened when they join, its folder moved aside when they're removed.
on_join: Callable[[User], None] = lambda user: None
on_remove: Callable[[User], None] = lambda user: None
lockout = LoginLockout()
# The password change's own waits, so strangers missing at /api/login can't stop a signed-in user changing it.
password_lockout = LoginLockout()
router = APIRouter()

# Each scrypt holds 16 MB, so strangers hammering the login can't add up to a few hundred of them. It gets
# its own two threads: a login waiting its turn then holds none of the pool every other sync route shares.
SCRYPT_AT_ONCE = 2
scrypt_pool = ThreadPoolExecutor(SCRYPT_AT_ONCE, thread_name_prefix="scrypt")
# Sign-ins from my own devices get a thread of their own, so they never wait behind strangers' (48 MB at most, all told).
my_scrypt_pool = ThreadPoolExecutor(1, thread_name_prefix="scrypt-mine")
# Strangers are every sign-in that isn't from my devices, friends over Funnel too, all sharing one allowance taken before
# the scrypt. Over it, the same 429 as a name's wait, with a Retry-After that's 1 for everyone, so it says nothing of a name.
STRANGER_SIGN_INS_PER_S = 2.0
STRANGER_SIGN_IN_BURST = 10.0
STRANGERS = "strangers"
stranger_sign_ins = TokenBucket(STRANGER_SIGN_INS_PER_S, STRANGER_SIGN_IN_BURST)
stranger_refusals = RefusalNote()
Result = TypeVar("Result")

logger = logging.getLogger(__name__)


async def run_scrypt_work(work: Callable[..., Result], *args, pool: ThreadPoolExecutor | None = None) -> Result:
    """For every call that hashes or checks a password: on scrypt_pool, or the pool given."""
    result = await asyncio.get_running_loop().run_in_executor(scrypt_pool if pool is None else pool, work, *args)
    return result


def refuse_strangers_past_the_cap(now: float) -> None:
    """Raises the 429 once strangers' sign-ins are past their allowance, with one journal line a minute at most."""
    if stranger_sign_ins.take(now) > 0:
        turned_away = stranger_refusals.count(STRANGERS, now)
        if turned_away:
            logger.warning("turned away %d strangers' sign-ins in the last minute", turned_away)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=TOO_MANY_TRIES, headers={"Retry-After": "1"})


@dataclass(frozen=True)
class Viewer:
    """Who a request is from. session is None when it came with a Mac helper token."""

    user: User
    session: Session | None


def is_from_my_devices(request: Request) -> bool:
    """Exactly one Tailscale-User-Login header, exactly DAYANPI_TAILSCALE_LOGIN (no case folding). Never when it's unset."""
    mine = bool(TAILSCALE_LOGIN) and request.headers.getlist(TAILSCALE_HEADER) == [TAILSCALE_LOGIN]
    return mine


def read_bearer(request: Request) -> str | None:
    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    bearer = credentials.strip() if scheme.lower() == "bearer" else None
    return bearer


def find_viewer(request: Request, now: float) -> Viewer | None:
    """A Mac helper token, only under /api/mac/ (the cookie is ignored then), or else the session cookie."""
    bearer = read_bearer(request)
    if bearer is not None:
        user = accounts.find_token_user(bearer, now) if request.scope["path"].startswith(MAC_PREFIX) else None
        viewer = None if user is None else Viewer(user, None)
    else:
        session = accounts.find_session(request.cookies.get(SESSION_COOKIE, ""), now)
        viewer = None if session is None else Viewer(session.user, session)
    return viewer


def read_viewer(request: Request) -> Viewer:
    """What the middleware found, on every route behind a sign-in."""
    viewer: Viewer = request.state.viewer
    return viewer


def set_session_cookie(response: Response, token: str) -> None:
    # The __Host- prefix makes the browser insist on Secure, Path=/ and no Domain, so no other host can plant one.
    response.set_cookie(SESSION_COOKIE, token, max_age=int(SESSION_TTL_S), path="/", secure=True, httponly=True, samesite="lax")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")


def describe_user(user: User) -> dict:
    described = {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role}
    return described


Username = Annotated[str, AfterValidator(check_username)]
DisplayName = Annotated[str, AfterValidator(check_display_name)]
NewPassword = Annotated[str, Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)]
TokenName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TOKEN_NAME_MAX)]
RowId = Annotated[int, PathParam(ge=1, le=2**63 - 1)]  # bigger than SQLite's integers would be a 500


class LoginBody(BaseModel):
    username: str = Field(max_length=256)
    password: str = Field(max_length=1024)  # the owner's password came from the env file, unchecked


class JoinBody(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    display_name: DisplayName
    username: Username
    password: NewPassword


class MeChange(BaseModel):
    display_name: DisplayName


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: NewPassword


class TokenNew(BaseModel):
    name: TokenName


@router.post("/api/login")
async def log_in(body: LoginBody, request: Request, response: Response):
    now = time.time()
    mine = is_from_my_devices(request)
    if not mine:
        refuse_strangers_past_the_cap(now)
    user = await run_scrypt_work(check_sign_in, accounts, lockout, body.username, body.password, now, mine, pool=my_scrypt_pool if mine else None)
    # A miss is the same 401 for every name. While a wait is on (from the miss that starts it) it's a 429 that says
    # how long, which tells nothing about the name either: unknown names wait the same way.
    wait = 0.0 if user is not None or mine else lockout.wait_left(normalize_username(body.username), now)
    if wait > 0:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=TOO_MANY_TRIES, headers={"Retry-After": str(math.ceil(wait))})
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=WRONG_LOGIN)
    set_session_cookie(response, accounts.create_session(user.id, now))
    return {"user": describe_user(user)}


@router.post("/api/logout")
def log_out(request: Request, response: Response):
    """Open without a session, and always clears the cookie."""
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        accounts.delete_session(token)
    clear_session_cookie(response)
    return {"status": "ok"}


@router.post("/api/join")
async def join(body: JoinBody, response: Response):
    """The code comes in the body, never the path, so it can't land in the access log."""
    now = time.time()
    try:
        user = await run_scrypt_work(accounts.join, body.code, body.display_name, body.username, body.password, now)
    except InviteNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="this invite doesn't work any more") from None
    except RoomFull:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ROOM_FULL) from None
    except UsernameTaken:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="that username is taken") from None
    on_join(user)
    set_session_cookie(response, accounts.create_session(user.id, now))
    return {"user": describe_user(user)}


@router.get("/api/me")
def read_me(request: Request):
    return {"user": describe_user(read_viewer(request).user)}


@router.patch("/api/me")
def change_me(change: MeChange, request: Request):
    user = accounts.rename(read_viewer(request).user.id, change.display_name)
    if user is None:  # removed a moment ago
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="sign in first")
    return {"user": describe_user(user)}


@router.post("/api/me/password")
async def change_password(change: PasswordChange, request: Request):
    """A wrong current password counts toward its own wait and the sign-in's. Ends the other sessions.

    This caller is signed in, so its own wait can say so instead of "wrong password"."""
    viewer = read_viewer(request)
    username = viewer.user.username
    now = time.time()
    if not password_lockout.reserve_attempt(username, now):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=TOO_MANY_TRIES)
    if await run_scrypt_work(accounts.check_login, username, change.current_password) is None:
        lockout.reserve_attempt(username, now)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="wrong password")
    password_lockout.clear(username)
    await run_scrypt_work(accounts.change_password, viewer.user.id, change.new_password, viewer.session.token_hash)
    return {"status": "ok"}


@router.get("/api/tokens")
def list_tokens(request: Request):
    tokens = accounts.list_tokens(read_viewer(request).user.id)
    return {"tokens": [asdict(token) for token in tokens]}


@router.post("/api/tokens")
def create_token(new: TokenNew, request: Request):
    """The only time the secret is shown; the Pi keeps its hash."""
    try:
        created = accounts.create_token(read_viewer(request).user.id, new.name, time.time())
    except TooManyTokens:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{TOKENS_MAX} tokens is the most. Delete one first.") from None
    return {"token": asdict(created.token), "secret": created.secret}


@router.delete("/api/tokens/{token_id}")
def delete_token(token_id: RowId, request: Request):
    if not accounts.delete_token(read_viewer(request).user.id, token_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no such token")
    return {"status": "ok"}


# The owner's alone from here on: the middleware turns members away (OWNER_READS, and every write by default).


@router.get("/api/invites")
def list_invites():
    invites = accounts.list_invites(time.time())
    return {"invites": [asdict(invite) for invite in invites]}


@router.post("/api/invites")
def create_invite():
    """The page turns the code into a /join/<code> link; the Pi only keeps its hash."""
    try:
        created = accounts.create_invite(time.time())
    except RoomFull:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ROOM_FULL) from None
    return {"invite": asdict(created.invite), "code": created.code}


@router.delete("/api/invites/{invite_id}")
def delete_invite(invite_id: RowId):
    if not accounts.delete_invite(invite_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no such invite")
    return {"status": "ok"}


@router.get("/api/accounts")
def list_accounts():
    users = accounts.list_users()
    return {"accounts": [asdict(user) for user in users]}


@router.delete("/api/accounts/{account_id}")
def delete_account(account_id: RowId):
    """Removes a member with its sessions and tokens, so it's signed out everywhere at once."""
    user = accounts.find_user(account_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no such account")
    if user.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="the owner can't be removed")
    accounts.delete_member(account_id)
    on_remove(user)
    return {"status": "ok"}
