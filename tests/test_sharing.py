import json

import pytest

from dayanpi.focus.sharing import DEFAULT_SHARING, HERE_S, NEEDS, NUDGE_AFTER_S, NUDGE_EVERY_S, PICTURE_MAX_AGE_S, SharingSetting, build_seat, can_nudge, is_here, share_parts

NOW = 1_800_000_000.0
# A desk's full status, with something to find for every part.
STATUS = {
    "state": "phone",
    "seconds_in_state": 365.0,
    "today": {"working_seconds": 6480.0, "phone_seconds": 1440.0, "pickups": 7},
    "app": "SecretApp",
    "site": "secret.example",
    "todos": {
        "current": "t2",
        "open": [{"id": "t1", "text": "open thing", "seconds": 1}, {"id": "t2", "text": "current thing", "seconds": 2}],
        "done": [{"id": "t3", "text": "done thing", "seconds": 3}],
    },
    "last_check": {"at": NOW - 1, "person": 0.9, "phone": 0.8},
    "voice": {"problem": "secret problem"},
    "bedtime": "23:30",
}
# What each switch lets out, as text that must never show while it's off.
PARTS = {"focus": ["focus_seconds", "6480"], "todos": ["current thing", '"todos"'], "apps": ["SecretApp"]}


def share(**on) -> dict:
    sharing = {key: False for key in DEFAULT_SHARING} | on
    return sharing


def test_the_switches_start_with_focus_todos_and_history_on(tmp_path):
    assert SharingSetting(tmp_path / "sharing.json").read() == {
        "focus": True, "todos": True, "history": True, "apps": False, "sites": False, "video": False, "nudges": True,
    }


def test_the_switches_are_saved_and_read_back(tmp_path):
    path = tmp_path / "desk" / "sharing.json"
    saved = SharingSetting(path).set({"apps": True, "focus": False, "status": False})
    assert saved == DEFAULT_SHARING | {"apps": True, "focus": False}, "status isn't a switch"
    assert SharingSetting(path).read() == saved
    assert json.loads(path.read_text()) == saved


def test_an_unreadable_file_means_the_defaults(tmp_path, caplog):
    path = tmp_path / "sharing.json"
    path.write_text("{nope")
    assert SharingSetting(path).read() == DEFAULT_SHARING
    assert "couldn't read" in caplog.text


@pytest.mark.parametrize("switch", sorted(PARTS))
def test_a_switched_off_part_is_nowhere_in_the_seat(switch):
    everything_but = share(**{key: True for key in DEFAULT_SHARING if key != switch})
    hidden = json.dumps(build_seat("sam", "Sam", STATUS, everything_but, here=True))
    shown = json.dumps(build_seat("sam", "Sam", STATUS, share(**{key: True for key in DEFAULT_SHARING}), here=True))
    for text in PARTS[switch]:
        assert text not in hidden
        assert text in shown


def test_status_always_shows_and_nothing_else_of_the_desk_ever_does():
    everything = share(**{key: True for key in DEFAULT_SHARING})
    assert build_seat("sam", "Sam", STATUS, everything, here=True, now=NOW) == {
        "username": "sam",
        "name": "Sam",
        "here": True,
        "state": "phone",
        "seconds_in_state": 365.0,
        "shares": ["focus", "todos", "apps", "sites", "video", "history"],
        "focus_seconds": 6480.0,
        "todos": {"current": "current thing", "current_seconds": 2, "done": 1, "total": 3},
        "app": "SecretApp",
        "site": "secret.example",
        "nudge": {"wait_s": 0.0, "age_s": None},
        "picture": None,  # shares video, but no picture right now
    }
    status_only = {"username": "sam", "name": "Sam", "here": True, "state": "phone", "seconds_in_state": 365.0, "shares": []}
    assert build_seat("sam", "Sam", STATUS, share(), here=True) == status_only


def test_sites_only_count_while_apps_is_on():
    assert "secret.example" not in json.dumps(build_seat("sam", "Sam", STATUS, share(sites=True), here=True))
    with_apps = build_seat("sam", "Sam", STATUS, share(apps=True), here=True)
    assert (with_apps["app"], "site" in with_apps) == ("SecretApp", False)
    assert build_seat("sam", "Sam", STATUS, share(sites=True), here=True)["shares"] == [], "sites alone shows nothing"


def test_someone_who_isnt_here_is_offline_with_no_timer():
    seat = build_seat("sam", "Sam", STATUS, share(focus=True), here=False)
    assert (seat["state"], seat["seconds_in_state"], seat["focus_seconds"]) == ("offline", None, 6480.0)


@pytest.mark.parametrize(
    "seen_at, checked_at, here",
    [
        (NOW - 5, None, True),  # the site open
        (None, NOW - HERE_S + 1, True),  # the camera checked them
        (NOW - HERE_S - 1, NOW - HERE_S - 1, False),  # both too long ago
        (None, None, False),
    ],
)
def test_here_is_the_site_open_or_tracking_in_the_last_two_minutes(seen_at, checked_at, here):
    status = {**STATUS, "last_check": None if checked_at is None else {"at": checked_at}}
    assert is_here(seen_at, status, NOW) is here


def test_the_gate_never_makes_a_part_whose_switches_are_off():
    made = []
    parts = {"apps": lambda: made.append("apps"), "sites": lambda: made.append("sites"), "day_focus": lambda: made.append("day")}
    shared = share_parts(share(apps=True, focus=True), parts)
    assert (set(shared), made) == ({"apps"}, ["apps"])
    assert set(share_parts(share(focus=True, history=True), parts)) == {"day_focus"}, "the group line needs focus and history"
    with pytest.raises(KeyError):
        share_parts(share(), {"something_new": lambda: 1})
    assert set(NEEDS["sites"]) == {"apps", "sites"}


def test_nudging_needs_the_phone_for_five_minutes_their_ok_and_ten_minutes_since_the_last():
    def seat(state="phone", seconds=NUDGE_AFTER_S, nudges=True, nudged=None, here=True):
        return build_seat("sam", "Sam", {**STATUS, "state": state, "seconds_in_state": seconds}, share(nudges=nudges), here, nudged, NOW)

    assert can_nudge(seat())
    assert not can_nudge(seat(seconds=NUDGE_AFTER_S - 1))
    assert not can_nudge(seat(state="working"))
    assert not can_nudge(seat(here=False))
    assert not can_nudge(seat(nudges=False))
    assert "nudge" not in seat(nudges=False), "nudges off: nothing about them leaves"
    recent = seat(nudged={"by": "dayan", "at": NOW - 60})
    assert (can_nudge(recent), recent["nudge"]) == (False, {"wait_s": NUDGE_EVERY_S - 60, "age_s": 60.0})
    assert can_nudge(seat(nudged={"by": "dayan", "at": NOW - NUDGE_EVERY_S}))


@pytest.mark.parametrize(
    "state, video, age, here, shown",
    [
        ("working", True, 1, True, True),
        ("phone", True, PICTURE_MAX_AGE_S, True, True),
        ("away", True, 1, True, False),  # away or unknown: no picture at all
        ("unknown", True, 1, True, False),
        ("working", True, PICTURE_MAX_AGE_S + 0.1, True, False),  # older than 3 s is no picture
        ("working", True, 1, False, False),  # not here
    ],
)
def test_a_seat_has_a_picture_only_while_sharing_at_the_desk_and_fresh(state, video, age, here, shown):
    picture = {"jpeg": b"secret jpeg", "at": NOW - age}
    seat = build_seat("sam", "Sam", {**STATUS, "state": state}, share(video=video), here, None, NOW, picture)
    assert seat["picture"] == ({"at": NOW - age} if shown else None)
    assert "secret jpeg" not in json.dumps(seat), "the stream only says there is one; the JPEG has its own route"


def test_with_video_off_the_seat_says_nothing_about_a_picture():
    seat = build_seat("sam", "Sam", STATUS, share(focus=True), True, None, NOW, {"jpeg": b"x", "at": NOW})
    assert "picture" not in seat
    assert NEEDS["picture"] == ("video",)
