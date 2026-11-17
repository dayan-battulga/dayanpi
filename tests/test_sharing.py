import json

import pytest

from dayanpi.focus.sharing import DEFAULT_SHARING, HERE_S, SharingSetting, build_seat, is_here

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
        "focus": True, "todos": True, "history": True, "apps": False, "sites": False, "video": False,
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
    assert build_seat("sam", "Sam", STATUS, everything, here=True) == {
        "username": "sam",
        "name": "Sam",
        "here": True,
        "state": "phone",
        "seconds_in_state": 365.0,
        "focus_seconds": 6480.0,
        "todos": {"current": "current thing", "done": 1, "total": 3},
        "app": "SecretApp",
        "site": "secret.example",
    }
    assert build_seat("sam", "Sam", STATUS, share(), here=True) == {"username": "sam", "name": "Sam", "here": True, "state": "phone", "seconds_in_state": 365.0}


def test_sites_only_count_while_apps_is_on():
    assert "secret.example" not in json.dumps(build_seat("sam", "Sam", STATUS, share(sites=True), here=True))
    with_apps = build_seat("sam", "Sam", STATUS, share(apps=True), here=True)
    assert (with_apps["app"], "site" in with_apps) == ("SecretApp", False)


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
