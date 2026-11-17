"""Accounts for the dashboard: users, sessions, invites and Mac helper tokens in one SQLite file.

It lives in data/accounts.db (DAYANPI_DATA_DIR overrides data/), made on first use. Passwords
are scrypt hashes with a salt per user. Sessions, invite codes and API tokens are long random
strings, so the database only keeps their sha256. Nothing here logs a password, a session, a
code or a token. Every time-based rule takes `now` from the caller, like the focus tracker.
"""

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from dayanpi.focus.tracker import find_data_dir

ACCOUNTS_FILE = "accounts.db"
MAX_ACCOUNTS = 4
INVITE_TTL_S = 7 * 24 * 3600.0
SESSION_TTL_S = 30 * 24 * 3600.0
SESSION_REFRESH_S = 3600.0  # a session is extended at most this often, so a request isn't a disk write
TOKEN_TOUCH_S = 60.0  # same for a token's last_used_at

PASSWORD_MIN = 10
PASSWORD_MAX = 256
DISPLAY_NAME_MAX = 40
TOKEN_NAME_MAX = 40
USERNAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]{1,31}")
RESERVED_USERNAMES = {"removed"}  # data/users/removed/ keeps the folders of removed accounts (focus/desks.py)

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_SALT_BYTES = 16

LOCKOUT_FREE_MISSES = 4
LOCKOUT_FIRST_WAIT_S = 30.0
LOCKOUT_MAX_WAIT_S = 15 * 60.0
LOCKOUT_BUCKET_BYTES = 2  # 65536 buckets

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    extended_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_hash TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    secret_hash TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    last_used_at REAL
);
"""
USER_COLUMNS = "u.id, u.username, u.display_name, u.role, u.created_at"


def find_accounts_path() -> Path:
    path = find_data_dir() / ACCOUNTS_FILE
    return path


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    role: str  # "owner" | "member"
    created_at: float


@dataclass(frozen=True)
class Session:
    user: User
    token_hash: str
    extended_at: float


@dataclass(frozen=True)
class Invite:
    id: int
    created_at: float
    expires_at: float


@dataclass(frozen=True)
class NewInvite:
    invite: Invite
    code: str = field(repr=False)


@dataclass(frozen=True)
class ApiToken:
    id: int
    name: str
    created_at: float
    last_used_at: float | None


@dataclass(frozen=True)
class NewToken:
    token: ApiToken
    secret: str = field(repr=False)


class InviteNotFound(Exception):
    """Unknown, used or expired."""


class RoomFull(Exception):
    """MAX_ACCOUNTS accounts already."""


class UsernameTaken(Exception):
    pass


def encode_b64(raw: bytes) -> str:
    text = base64.b64encode(raw).decode("ascii")
    return text


def run_scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    """Each one holds 16 MB, so the routes run it in routes.scrypt_pool, two at a time."""
    # surrogatepass: os.environ hands an env file's non-UTF-8 bytes over as lone surrogates (pydantic turns them
    # away at the routes, so only the owner seeded from DAYANPI_PASSWORD can have one).
    digest = hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt, n=n, r=r, p=p, dklen=dklen)
    return digest


def hash_password(password: str) -> str:
    """"scrypt$n$r$p$salt$hash", so the parameters can change later without breaking old hashes."""
    salt = secrets.token_bytes(SCRYPT_SALT_BYTES)
    digest = run_scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN)
    stored = "$".join(["scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), encode_b64(salt), encode_b64(digest)])
    return stored


def check_password(password: str, stored: str) -> bool:
    """False for a wrong password and for a hash string that isn't one of ours."""
    matches = False
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        expected = base64.b64decode(digest, validate=True)
        if kind == "scrypt":
            actual = run_scrypt(password, base64.b64decode(salt, validate=True), int(n), int(r), int(p), len(expected))
            matches = hmac.compare_digest(actual, expected)
    except ValueError:  # wrong field count, bad base64 or numbers, scrypt refusing the parameters
        matches = False
    return matches


# Unknown usernames are checked against this, so a reply takes as long whether the name exists or not.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def hash_secret(secret: str) -> str:
    """Sessions, invite codes and tokens are 144+ random bits, so plain sha256 is enough."""
    digest = hashlib.sha256(secret.encode("utf-8", "surrogatepass")).hexdigest()
    return digest


def normalize_username(value: str) -> str:
    name = value.strip().lower()
    return name


def check_username(value: str) -> str:
    """The username to store. Raises ValueError (a 422 at the routes) when it doesn't fit the pattern."""
    name = normalize_username(value)
    if USERNAME_PATTERN.fullmatch(name) is None:
        raise ValueError("a username is 2 to 32 of a-z, 0-9, _ . - and starts with a letter or a digit")
    if name in RESERVED_USERNAMES:
        raise ValueError("that username is taken")
    return name


def check_display_name(value: str) -> str:
    name = value.strip()
    if not 1 <= len(name) <= DISPLAY_NAME_MAX or any(unicodedata.category(char) == "Cc" for char in name):
        raise ValueError(f"a display name is 1 to {DISPLAY_NAME_MAX} characters, with no control characters")
    return name


def read_user(row: sqlite3.Row) -> User:
    user = User(row["id"], row["username"], row["display_name"], row["role"], row["created_at"])
    return user


class AccountStore:
    """One connection and one lock around every use of it. scrypt always runs outside the lock."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._db: sqlite3.Connection | None = None

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            db = self._open()
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def _open(self) -> sqlite3.Connection:
        if self._db is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            db.executescript(SCHEMA)
            os.chmod(self._path, 0o600)  # password hashes: nobody else on the Pi needs to read them
            self._db = db
        return self._db

    def seed_owner(self, username: str, password: str, now: float) -> bool:
        """Makes the owner from DAYANPI_USER / DAYANPI_PASSWORD when there are no users yet. Returns whether it did.

        Neither goes through the join rules: the name is only stripped and lowercased, the password taken as is.
        """
        password_hash = hash_password(password)
        with self._transaction() as db:
            empty = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            if empty:
                db.execute(
                    "INSERT INTO users (username, display_name, role, password_hash, created_at) VALUES (?, ?, 'owner', ?, ?)",
                    (normalize_username(username), username.strip()[:DISPLAY_NAME_MAX], password_hash, now),
                )
        return empty

    def check_login(self, username: str, password: str) -> User | None:
        with self._transaction() as db:
            row = db.execute(
                f"SELECT {USER_COLUMNS}, u.password_hash FROM users u WHERE u.username = ?", (normalize_username(username),)
            ).fetchone()
        matches = check_password(password, DUMMY_HASH if row is None else row["password_hash"])
        user = read_user(row) if row is not None and matches else None
        return user

    def find_user(self, user_id: int) -> User | None:
        with self._transaction() as db:
            row = db.execute(f"SELECT {USER_COLUMNS} FROM users u WHERE u.id = ?", (user_id,)).fetchone()
        user = None if row is None else read_user(row)
        return user

    def list_users(self) -> list[User]:
        with self._transaction() as db:
            rows = db.execute(f"SELECT {USER_COLUMNS} FROM users u ORDER BY u.id").fetchall()
        users = [read_user(row) for row in rows]
        return users

    def rename(self, user_id: int, display_name: str) -> User | None:
        with self._transaction() as db:
            db.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, user_id))
        user = self.find_user(user_id)
        return user

    def change_password(self, user_id: int, new_password: str, keep_token_hash: str) -> None:
        """Also ends every other session of this user, so a stolen one stops working."""
        password_hash = hash_password(new_password)
        with self._transaction() as db:
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
            db.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, keep_token_hash))

    def delete_member(self, user_id: int) -> bool:
        """Never the owner. Its sessions and tokens go with it (ON DELETE CASCADE)."""
        with self._transaction() as db:
            deleted = db.execute("DELETE FROM users WHERE id = ? AND role = 'member'", (user_id,)).rowcount > 0
        return deleted

    def create_session(self, user_id: int, now: float) -> str:
        """Returns the cookie value; only its hash is kept."""
        token = secrets.token_urlsafe(32)
        with self._transaction() as db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            db.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, extended_at) VALUES (?, ?, ?, ?, ?)",
                (hash_secret(token), user_id, now, now + SESSION_TTL_S, now),
            )
        return token

    def find_session(self, token: str, now: float) -> Session | None:
        """Read only, apart from deleting an expired session. extend_session() does the refresh."""
        session = None
        if token:
            token_hash = hash_secret(token)
            with self._transaction() as db:
                row = db.execute(
                    f"SELECT {USER_COLUMNS}, s.expires_at, s.extended_at FROM sessions s JOIN users u ON u.id = s.user_id "
                    "WHERE s.token_hash = ?",
                    (token_hash,),
                ).fetchone()
                if row is not None and row["expires_at"] <= now:
                    db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                    row = None
            session = None if row is None else Session(read_user(row), token_hash, row["extended_at"])
        return session

    def extend_session(self, token_hash: str, now: float) -> None:
        with self._transaction() as db:
            db.execute(
                "UPDATE sessions SET expires_at = ?, extended_at = ? WHERE token_hash = ?",
                (now + SESSION_TTL_S, now, token_hash),
            )

    def delete_session(self, token: str) -> None:
        with self._transaction() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_secret(token),))

    def create_invite(self, now: float) -> NewInvite:
        """Raises RoomFull when there are MAX_ACCOUNTS accounts already."""
        code = secrets.token_urlsafe(18)
        with self._transaction() as db:
            if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= MAX_ACCOUNTS:
                raise RoomFull
            cursor = db.execute(
                "INSERT INTO invites (code_hash, created_at, expires_at) VALUES (?, ?, ?)",
                (hash_secret(code), now, now + INVITE_TTL_S),
            )
        created = NewInvite(Invite(cursor.lastrowid, now, now + INVITE_TTL_S), code)
        return created

    def list_invites(self, now: float) -> list[Invite]:
        """Unused and unexpired; a used invite is deleted."""
        with self._transaction() as db:
            rows = db.execute("SELECT id, created_at, expires_at FROM invites WHERE expires_at > ? ORDER BY id", (now,)).fetchall()
        invites = [Invite(row["id"], row["created_at"], row["expires_at"]) for row in rows]
        return invites

    def delete_invite(self, invite_id: int) -> bool:
        with self._transaction() as db:
            deleted = db.execute("DELETE FROM invites WHERE id = ?", (invite_id,)).rowcount > 0
        return deleted

    def join(self, code: str, display_name: str, username: str, password: str, now: float) -> User:
        """Uses the invite and makes a member in one transaction, so no race can reuse an invite or make a 5th account.

        Raises InviteNotFound, RoomFull or UsernameTaken (checked in that order); nothing changes then.
        username and display_name come already checked (check_username, check_display_name).
        """
        password_hash = hash_password(password)
        with self._transaction() as db:
            invite = db.execute(
                "SELECT id FROM invites WHERE code_hash = ? AND expires_at > ?", (hash_secret(code), now)
            ).fetchone()
            if invite is None:
                raise InviteNotFound
            if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= MAX_ACCOUNTS:
                raise RoomFull
            if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is not None:
                raise UsernameTaken
            db.execute("DELETE FROM invites WHERE id = ?", (invite["id"],))
            cursor = db.execute(
                "INSERT INTO users (username, display_name, role, password_hash, created_at) VALUES (?, ?, 'member', ?, ?)",
                (username, display_name, password_hash, now),
            )
        user = User(cursor.lastrowid, username, display_name, "member", now)
        return user

    def create_token(self, user_id: int, name: str, now: float) -> NewToken:
        secret = "dpi_" + secrets.token_urlsafe(32)
        with self._transaction() as db:
            cursor = db.execute(
                "INSERT INTO tokens (user_id, name, secret_hash, created_at) VALUES (?, ?, ?, ?)",
                (user_id, name, hash_secret(secret), now),
            )
        created = NewToken(ApiToken(cursor.lastrowid, name, now, None), secret)
        return created

    def list_tokens(self, user_id: int) -> list[ApiToken]:
        with self._transaction() as db:
            rows = db.execute(
                "SELECT id, name, created_at, last_used_at FROM tokens WHERE user_id = ? ORDER BY id", (user_id,)
            ).fetchall()
        tokens = [ApiToken(row["id"], row["name"], row["created_at"], row["last_used_at"]) for row in rows]
        return tokens

    def delete_token(self, user_id: int, token_id: int) -> bool:
        """Only the user's own; someone else's is the same False as an unknown one."""
        with self._transaction() as db:
            deleted = db.execute("DELETE FROM tokens WHERE id = ? AND user_id = ?", (token_id, user_id)).rowcount > 0
        return deleted

    def find_token_user(self, secret: str, now: float) -> User | None:
        user = None
        if secret:
            with self._transaction() as db:
                row = db.execute(
                    f"SELECT {USER_COLUMNS}, t.id AS token_id, t.last_used_at FROM tokens t JOIN users u ON u.id = t.user_id "
                    "WHERE t.secret_hash = ?",
                    (hash_secret(secret),),
                ).fetchone()
                if row is not None and (row["last_used_at"] is None or now - row["last_used_at"] >= TOKEN_TOUCH_S):
                    db.execute("UPDATE tokens SET last_used_at = ? WHERE id = ?", (now, row["token_id"]))
            user = None if row is None else read_user(row)
        return user


@dataclass(slots=True)
class MissCount:
    misses: int = 0
    wait_s: float = 0.0
    until: float = 0.0


class LoginLockout:
    """Wrong-password waits per lowercased username, known or not, so a wait can't tell which names exist.

    Misses 1-4 are free; the 5th starts a 30 s wait, and each miss after a wait doubles it, up to 15 min.
    Names go into 65536 buckets by a hash with a key made at startup: strangers can't grow it, can't push
    a name's wait out with a flood of other names, and can't pick a name that shares a bucket with yours.
    ponytail: in memory, so a restart clears every wait, and two names in one bucket share a wait.
    Move it into accounts.db if that ever matters.
    """

    def __init__(self) -> None:
        self._counts: dict[int, MissCount] = {}
        self._key = secrets.token_bytes(16)
        self._lock = threading.Lock()

    def _find_bucket(self, username: str) -> int:
        digest = hashlib.blake2b(username.encode("utf-8", "surrogatepass"), digest_size=LOCKOUT_BUCKET_BYTES, key=self._key)
        bucket = int.from_bytes(digest.digest(), "big")
        return bucket

    def reserve_attempt(self, username: str, now: float) -> bool:
        """Whether this attempt may check its password. It counts as a miss right here, before the check, so a
        burst of attempts can't all slip in before the first miss lands; clear() takes it back on a success.
        During a wait it's False and doesn't count."""
        bucket = self._find_bucket(username)
        with self._lock:
            count = self._counts.setdefault(bucket, MissCount())
            allowed = now >= count.until
            if allowed:
                count.misses += 1
                if count.misses > LOCKOUT_FREE_MISSES:
                    count.wait_s = min(count.wait_s * 2, LOCKOUT_MAX_WAIT_S) if count.wait_s else LOCKOUT_FIRST_WAIT_S
                    count.until = now + count.wait_s
        return allowed

    def wait_left(self, username: str, now: float) -> float:
        """Seconds until this name may try again, 0 when it may now. Right after the miss that starts a wait, it's all of it."""
        bucket = self._find_bucket(username)
        with self._lock:
            count = self._counts.get(bucket)
            left = 0.0 if count is None else max(0.0, count.until - now)
        return left

    def clear(self, username: str) -> None:
        bucket = self._find_bucket(username)
        with self._lock:
            self._counts.pop(bucket, None)


def check_sign_in(
    store: AccountStore, lockout: LoginLockout, username: str, password: str, now: float, from_my_devices: bool = False
) -> User | None:
    """The user, or None for an unknown name, a wrong password or a wait alike. During a wait the password isn't checked.

    From the owner's own Tailscale devices the lockout isn't touched at all: no wait, a miss doesn't count, and a
    success doesn't clear the wait strangers ran up, so the internet still waits it out.
    """
    key = normalize_username(username)
    if from_my_devices:
        user = store.check_login(key, password)
    else:
        user = store.check_login(key, password) if lockout.reserve_attempt(key, now) else None
        if user is not None:
            lockout.clear(key)
    return user
