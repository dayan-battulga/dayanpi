import os
import sqlite3
import stat
import threading
import time
from contextlib import contextmanager

import pytest

from dayanpi.auth import accounts
from dayanpi.auth.accounts import (
    INVITE_TTL_S,
    SESSION_TTL_S,
    AccountStore,
    InviteNotFound,
    LoginLockout,
    RoomFull,
    UsernameTaken,
    check_display_name,
    check_password,
    check_sign_in,
    check_username,
    hash_password,
)

NOW = 1_800_000_000.0
PASSWORD = "a long enough password"


@pytest.fixture
def store(tmp_path):
    return AccountStore(tmp_path / "accounts.db")


def add_member(store, username, now=NOW):
    invite = store.create_invite(now)
    return store.join(invite.code, username.title(), username, PASSWORD, now)


def test_a_password_checks_against_its_own_hash_only():
    stored = hash_password("correct horse battery")
    assert stored.startswith("scrypt$16384$8$1$")
    assert check_password("correct horse battery", stored)
    assert not check_password("correct horse batterY", stored)
    assert hash_password("correct horse battery") != stored, "a new salt every time"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda stored: stored[:-6] + ("AAAAA=" if not stored.endswith("AAAAA=") else "BBBBB="),  # another hash
        lambda stored: stored.replace("scrypt$", "md5$"),
        lambda stored: stored.replace("$16384$", "$16383$"),  # n must be a power of two
        lambda stored: stored.replace("$16384$", "$1099511627776$"),  # way past scrypt's memory limit
        lambda stored: stored.rsplit("$", 1)[0] + "$not base64!",
        lambda stored: stored.rsplit("$", 1)[0],
        lambda stored: "",
    ],
)
def test_a_tampered_hash_string_never_matches(tamper):
    stored = hash_password("correct horse battery")
    assert not check_password("correct horse battery", tamper(stored))


def test_the_database_is_made_on_first_use_and_only_the_pi_user_reads_it(tmp_path):
    path = tmp_path / "data" / "accounts.db"
    store = AccountStore(path)
    assert not path.exists()
    store.list_users()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_the_owner_is_made_only_on_an_empty_database(store):
    assert store.seed_owner("  Dayan ", "short", NOW) is True
    assert store.seed_owner("someone", "else", NOW) is False
    [owner] = store.list_users()
    assert (owner.username, owner.display_name, owner.role) == ("dayan", "Dayan", "owner")
    assert store.check_login("DAYAN", "short") == owner, "the env password is taken as is, the name lowercased"
    assert store.check_login("dayan", "wrong") is None
    assert store.check_login("nobody", "short") is None


def test_an_unknown_username_still_runs_scrypt(store, monkeypatch):
    store.seed_owner("dayan", "the owner password", NOW)
    checked = []

    def check_and_note(password, stored):
        checked.append(stored)
        return True  # even a "match" against the dummy hash must not sign anyone in

    monkeypatch.setattr(accounts, "check_password", check_and_note)
    assert store.check_login("nobody", "the owner password") is None
    assert checked == [accounts.DUMMY_HASH], "an unknown name answers as slowly as a real one"


def join_at_once(store, codes, monkeypatch):
    """One thread per code, all calling join() at the same moment. Returns what each one got: a User or the exception."""
    start = threading.Barrier(len(codes))
    outcomes = [None] * len(codes)
    run_transaction = store._transaction

    # A thread that just let go of the lock usually takes it right back, which would hide a join split over two
    # transactions; this pause lets the other threads in between any two.
    @contextmanager
    def pause_after_transaction():
        with run_transaction() as db:
            yield db
        time.sleep(0.05)

    monkeypatch.setattr(store, "_transaction", pause_after_transaction)

    def join(index, code):
        start.wait(5)
        try:
            outcomes[index] = store.join(code, f"Racer {index}", f"racer{index}", PASSWORD, NOW)
        except (InviteNotFound, RoomFull) as refused:
            outcomes[index] = refused

    racers = [threading.Thread(target=join, args=(index, code)) for index, code in enumerate(codes)]
    for thread in racers:
        thread.start()
    for thread in racers:
        thread.join(30)
    return outcomes


def test_one_invite_opened_at_once_by_many_makes_one_account(store, monkeypatch):
    store.seed_owner("dayan", "pw", NOW)
    invite = store.create_invite(NOW)
    outcomes = join_at_once(store, [invite.code] * 6, monkeypatch)
    assert sum(isinstance(outcome, accounts.User) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, InviteNotFound) for outcome in outcomes) == 5
    assert len(store.list_users()) == 2


def test_the_last_seat_taken_at_once_makes_no_fifth_account(store, monkeypatch):
    store.seed_owner("dayan", "pw", NOW)
    for name in ("bo", "cy"):
        add_member(store, name)
    invites = [store.create_invite(NOW).code for _ in range(4)]
    outcomes = join_at_once(store, invites, monkeypatch)
    assert sum(isinstance(outcome, accounts.User) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, RoomFull) for outcome in outcomes) == 3
    assert len(store.list_users()) == 4


def test_an_invite_works_once(store):
    invite = store.create_invite(NOW)
    assert [found.id for found in store.list_invites(NOW)] == [invite.invite.id]
    member = store.join(invite.code, "Bo", "bo", PASSWORD, NOW)
    assert (member.username, member.role) == ("bo", "member")
    assert store.check_login("bo", PASSWORD) == member
    with pytest.raises(InviteNotFound):
        store.join(invite.code, "Cy", "cy", PASSWORD, NOW)
    assert store.list_invites(NOW) == []


def test_an_invite_expires_after_seven_days(store):
    invite = store.create_invite(NOW)
    assert store.list_invites(NOW + INVITE_TTL_S) == []
    with pytest.raises(InviteNotFound):
        store.join(invite.code, "Bo", "bo", PASSWORD, NOW + INVITE_TTL_S)
    assert store.join(invite.code, "Bo", "bo", PASSWORD, NOW + INVITE_TTL_S - 1).username == "bo"


def test_a_made_up_code_never_costs_a_scrypt(store, monkeypatch):
    """Funnel lets anyone try codes, so a guess must be cheap for the Pi. A real code still hashes the password."""
    hashed = []
    real_hash = accounts.hash_password
    monkeypatch.setattr(accounts, "hash_password", lambda password: hashed.append(password) or real_hash(password))
    expired = store.create_invite(NOW - INVITE_TTL_S)
    for code in ("made-up", expired.code):
        with pytest.raises(InviteNotFound):
            store.join(code, "Bo", "bo", PASSWORD, NOW)
    assert hashed == []
    assert add_member(store, "bo").username == "bo"
    assert hashed == [PASSWORD]


def test_a_wrong_code_and_a_deleted_invite_do_not_work(store):
    invite = store.create_invite(NOW)
    with pytest.raises(InviteNotFound):
        store.join(invite.code + "x", "Bo", "bo", PASSWORD, NOW)
    assert store.delete_invite(invite.invite.id) is True
    assert store.delete_invite(invite.invite.id) is False
    with pytest.raises(InviteNotFound):
        store.join(invite.code, "Bo", "bo", PASSWORD, NOW)


def test_a_taken_username_keeps_the_invite_for_another_try(store):
    store.seed_owner("dayan", "pw", NOW)
    invite = store.create_invite(NOW)
    with pytest.raises(UsernameTaken):
        store.join(invite.code, "Imposter", "dayan", PASSWORD, NOW)
    assert store.join(invite.code, "Bo", "bo", PASSWORD, NOW).username == "bo"


def test_no_fifth_account(store):
    store.seed_owner("dayan", "pw", NOW)
    early = store.create_invite(NOW)  # made while there was room
    for name in ("bo", "cy", "di"):
        add_member(store, name)
    with pytest.raises(RoomFull):
        store.create_invite(NOW)
    with pytest.raises(RoomFull):
        store.join(early.code, "Ed", "ed", PASSWORD, NOW)
    assert len(store.list_users()) == 4
    assert len(store.list_invites(NOW)) == 1, "a refused join leaves the invite alone"


def test_removing_a_member_frees_a_seat_but_the_owner_stays(store):
    store.seed_owner("dayan", "pw", NOW)
    [owner] = store.list_users()
    members = [add_member(store, name) for name in ("bo", "cy", "di")]
    assert store.delete_member(owner.id) is False
    assert store.delete_member(members[0].id) is True
    assert store.find_user(members[0].id) is None
    assert store.create_invite(NOW).code


def test_ids_of_removed_accounts_tokens_and_invites_are_never_reused(store):
    # A stale Settings tab, or anything kept per user id, must never land on the next one made.
    gone = add_member(store, "bo")
    store.delete_member(gone.id)
    kept = add_member(store, "cy")
    assert kept.id > gone.id
    revoked = store.create_token(kept.id, "mac", NOW)
    store.delete_token(kept.id, revoked.token.id)
    assert store.create_token(kept.id, "mac", NOW).token.id > revoked.token.id
    deleted = store.create_invite(NOW)
    store.delete_invite(deleted.invite.id)
    assert store.create_invite(NOW).invite.id > deleted.invite.id


def test_a_session_lasts_thirty_days_from_its_last_refresh(store):
    member = add_member(store, "bo")
    token = store.create_session(member.id, NOW)
    session = store.find_session(token, NOW + 10)
    assert session.user == member and session.extended_at == NOW
    store.extend_session(session.token_hash, NOW + 100)
    assert store.find_session(token, NOW + SESSION_TTL_S + 50).extended_at == NOW + 100
    assert store.find_session(token, NOW + 100 + SESSION_TTL_S) is None
    assert store.find_session(token, NOW) is None, "an expired session is deleted, not just refused"


def test_a_session_ends_on_sign_out_and_with_its_account(store):
    member = add_member(store, "bo")
    first = store.create_session(member.id, NOW)
    second = store.create_session(member.id, NOW)
    store.delete_session(first)
    assert store.find_session(first, NOW) is None
    assert store.find_session(second, NOW) is not None
    token = store.create_token(member.id, "mac", NOW)
    store.delete_member(member.id)
    assert store.find_session(second, NOW) is None
    assert store.find_token_user(token.secret, NOW) is None
    assert store.find_session("", NOW) is None


def test_the_database_keeps_only_hashes(store, tmp_path):
    store.seed_owner("dayan", "the owner password", NOW)
    member = add_member(store, "bo")
    session = store.create_session(member.id, NOW)
    invite = store.create_invite(NOW)
    token = store.create_token(member.id, "mac", NOW)
    raw = (tmp_path / "accounts.db").read_bytes()
    for secret in ("the owner password", PASSWORD, session, invite.code, token.secret):
        assert secret.encode() not in raw
    assert token.secret.startswith("dpi_")
    assert invite.code not in repr(invite) and token.secret not in repr(token)


def test_changing_the_password_ends_the_other_sessions(store):
    member = add_member(store, "bo")
    kept = store.create_session(member.id, NOW)
    other = store.create_session(member.id, NOW)
    store.change_password(member.id, "a brand new password", store.find_session(kept, NOW).token_hash)
    assert store.find_session(kept, NOW) is not None
    assert store.find_session(other, NOW) is None
    assert store.check_login("bo", "a brand new password") is not None
    assert store.check_login("bo", PASSWORD) is None


def test_tokens_are_per_user_and_revocable(store):
    store.seed_owner("dayan", "pw", NOW)
    [owner] = store.list_users()
    member = add_member(store, "bo")
    mine = store.create_token(member.id, "mac", NOW)
    theirs = store.create_token(owner.id, "laptop", NOW)
    assert store.find_token_user(mine.secret, NOW + 5) == member
    assert [token.name for token in store.list_tokens(member.id)] == ["mac"]
    assert store.delete_token(member.id, theirs.token.id) is False, "not someone else's"
    assert store.find_token_user(theirs.secret, NOW) == owner
    assert store.delete_token(member.id, mine.token.id) is True
    assert store.find_token_user(mine.secret, NOW) is None
    assert store.find_token_user("", NOW) is None


def test_a_token_notes_its_last_use_at_most_once_a_minute(store):
    member = add_member(store, "bo")
    token = store.create_token(member.id, "mac", NOW)
    store.find_token_user(token.secret, NOW + 10)
    store.find_token_user(token.secret, NOW + 30)
    assert store.list_tokens(member.id)[0].last_used_at == NOW + 10
    store.find_token_user(token.secret, NOW + 70)
    assert store.list_tokens(member.id)[0].last_used_at == NOW + 70


def test_renaming_keeps_everything_else(store):
    member = add_member(store, "bo")
    renamed = store.rename(member.id, "Bo B.")
    assert (renamed.display_name, renamed.username, renamed.id) == ("Bo B.", "bo", member.id)


def test_foreign_keys_are_on(store):
    store.list_users()
    with pytest.raises(sqlite3.IntegrityError):
        store.create_session(12345, NOW)


@pytest.mark.parametrize("raw, expected", [("  Bo.B_1 ", "bo.b_1"), ("ZED", "zed"), ("a1", "a1")])
def test_usernames_are_stripped_and_lowercased(raw, expected):
    assert check_username(raw) == expected


@pytest.mark.parametrize("raw", ["a", "_bo", ".bo", "bo b", "bø", "x" * 33, "", "bo/..", "b\no"])
def test_bad_usernames_are_refused(raw):
    with pytest.raises(ValueError):
        check_username(raw)


def test_display_names_are_stripped_short_and_printable():
    assert check_display_name("  Bo 🎧 ") == "Bo 🎧"
    for bad in ("", "   ", "x" * 41, "Bo\x00", "Bo\nB", "Bo\x7f", "B\u0085o"):
        with pytest.raises(ValueError):
            check_display_name(bad)


def test_the_lockout_waits_30_s_after_five_misses_and_doubles_to_15_min():
    lockout = LoginLockout()
    now = NOW
    assert [lockout.reserve_attempt("bo", now) for _ in range(6)] == [True] * 5 + [False]
    waits = []
    for _ in range(7):
        start = now
        while not lockout.reserve_attempt("bo", now):
            now += 1
        waits.append(now - start)
    assert waits == [30, 60, 120, 240, 480, 900, 900]


def test_a_try_during_a_wait_does_not_count():
    lockout = LoginLockout()
    for _ in range(5):
        lockout.reserve_attempt("bo", NOW)
    assert not lockout.reserve_attempt("bo", NOW + 10)
    assert not lockout.reserve_attempt("bo", NOW + 29)
    assert lockout.reserve_attempt("bo", NOW + 30), "still the 30 s wait, not a doubled one"


def test_a_flood_of_other_names_never_resets_a_wait():
    lockout = LoginLockout()
    for _ in range(5):
        lockout.reserve_attempt("dayan", NOW)
    for index in range(20_000):
        lockout.reserve_attempt(f"spray{index}", NOW + 10)
    assert not lockout.reserve_attempt("dayan", NOW + 29), "the 30 s wait is still on"
    # A flood takes minutes on the Pi, so the wait is usually over by the time it's done. Names sharing
    # dayan's bucket are left out here: they would count toward the same wait, which is fine but not this test.
    others = [f"late{index}" for index in range(20_000) if lockout._find_bucket(f"late{index}") != lockout._find_bucket("dayan")]
    for name in others:
        lockout.reserve_attempt(name, NOW + 35)
    assert lockout.reserve_attempt("dayan", NOW + 40)
    assert not lockout.reserve_attempt("dayan", NOW + 99), "that miss doubled the wait to 60 s, as if no flood came"
    assert len(lockout._counts) <= 2 ** (8 * accounts.LOCKOUT_BUCKET_BYTES)


def test_a_burst_of_sign_ins_checks_only_five_passwords(store, monkeypatch):
    """40 wrong guesses at once, like 40 requests on 40 threads: all of them start before the first check is done."""
    store.seed_owner("dayan", "the owner password", NOW)
    lockout = LoginLockout()
    start = threading.Barrier(40)
    checked = []

    def check_slowly(password, stored):
        checked.append(password)
        time.sleep(0.3)
        return False

    def guess(index):
        start.wait(5)
        check_sign_in(store, lockout, "dayan", f"guess {index}", NOW)

    monkeypatch.setattr(accounts, "check_password", check_slowly)
    guesses = [threading.Thread(target=guess, args=(index,)) for index in range(40)]
    for thread in guesses:
        thread.start()
    for thread in guesses:
        thread.join(10)
    assert len(checked) == 5


def test_sign_in_refuses_the_right_password_during_a_wait_and_clears_on_success(store):
    store.seed_owner("dayan", "the owner password", NOW)
    lockout = LoginLockout()
    for _ in range(5):
        assert check_sign_in(store, lockout, "Dayan", "wrong", NOW) is None
    assert check_sign_in(store, lockout, "dayan", "the owner password", NOW + 29) is None
    assert check_sign_in(store, lockout, "dayan", "the owner password", NOW + 30).username == "dayan"
    for _ in range(4):
        assert check_sign_in(store, lockout, "dayan", "wrong", NOW + 31) is None
    assert check_sign_in(store, lockout, "dayan", "the owner password", NOW + 31) is not None, "a success starts the count over"


def test_from_my_devices_a_sign_in_never_waits_and_its_misses_do_not_count(store):
    store.seed_owner("dayan", "the owner password", NOW)
    lockout = LoginLockout()
    for _ in range(10):
        assert check_sign_in(store, lockout, "dayan", "my typo", NOW, from_my_devices=True) is None
    assert check_sign_in(store, lockout, "dayan", "the owner password", NOW) is not None, "the typos never counted"
    for _ in range(5):
        check_sign_in(store, lockout, "dayan", "a stranger's guess", NOW)
    assert check_sign_in(store, lockout, "dayan", "the owner password", NOW + 1) is None, "the internet waits"
    assert check_sign_in(store, lockout, "Dayan", "the owner password", NOW + 1, from_my_devices=True).username == "dayan"
    assert check_sign_in(store, lockout, "dayan", "the owner password", NOW + 2) is None, "and still waits after I sign in"


def test_unknown_usernames_get_the_same_lockout(store):
    lockout = LoginLockout()
    for _ in range(5):
        assert check_sign_in(store, lockout, "nobody", "guess", NOW) is None
    assert not lockout.reserve_attempt("nobody", NOW + 1)
