import logging
from datetime import datetime

import pytest

from dayanpi.auth.accounts import check_username
from dayanpi.focus.desks import Desks, move_owner_data

NOW = datetime(2026, 11, 16, 19, 12).timestamp()


def write_old_data(data_dir):
    """The owner's data the way it sat right in data/ before everyone had a desk."""
    (data_dir / "focus_log").mkdir(parents=True)
    (data_dir / "focus_log" / "2026-11-15.jsonl").write_bytes(b'{"event":"state","state":"working"}\n')
    (data_dir / "focus_log" / "2026-11-16.jsonl").write_bytes(b'{"event":"sample"}\n')
    (data_dir / "days").mkdir()
    (data_dir / "days" / "2026-11-15.md").write_bytes(b"---\nfocus_minutes: 95\n---\n")
    (data_dir / "todos.json").write_bytes(b'{"current": null, "items": []}')
    (data_dir / "mac_tracking.json").write_bytes(b'{"enabled": false}')


def read_tree(folder) -> dict[str, bytes]:
    """Every file under folder by its path inside it, with its bytes."""
    files = {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}
    return files


def test_my_data_moves_into_my_folder_once_byte_for_byte(tmp_path, caplog):
    write_old_data(tmp_path)
    before = read_tree(tmp_path)
    folder = tmp_path / "users" / "dayan"
    with caplog.at_level(logging.INFO, logger="dayanpi"):
        moved = move_owner_data(tmp_path, folder)
    assert moved == ["focus_log", "todos.json", "days", "mac_tracking.json"]
    assert read_tree(folder) == before
    assert read_tree(tmp_path) == {f"users/dayan/{name}": data for name, data in before.items()}, "nothing copied, nothing left"
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 1 and "moved focus_log, todos.json, days, mac_tracking.json" in messages[0]

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="dayanpi"):
        again = move_owner_data(tmp_path, folder)
    assert again == []
    assert caplog.records == [], "a second start does nothing, quietly"
    assert read_tree(folder) == before


def test_nothing_moves_when_something_is_in_both_places(tmp_path, caplog):
    write_old_data(tmp_path)
    folder = tmp_path / "users" / "dayan"
    folder.mkdir(parents=True)
    (folder / "todos.json").write_bytes(b"already here")
    before = read_tree(tmp_path)
    with caplog.at_level(logging.INFO, logger="dayanpi"):
        moved = move_owner_data(tmp_path, folder)
    assert moved == []
    assert read_tree(tmp_path) == before, "neither copy touched"
    errors = [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(errors) == 1 and "todos.json" in errors[0]


def test_a_move_cut_short_moves_the_rest_next_time(tmp_path):
    write_old_data(tmp_path)
    folder = tmp_path / "users" / "dayan"
    folder.mkdir(parents=True)
    (tmp_path / "focus_log").rename(folder / "focus_log")
    assert move_owner_data(tmp_path, folder) == ["todos.json", "days", "mac_tracking.json"]


def test_there_is_nothing_to_move_on_a_new_pi(tmp_path):
    assert move_owner_data(tmp_path, tmp_path / "users" / "dayan") == []
    assert not (tmp_path / "users").exists()


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b", "a\x00b", "removed"])
def test_a_desk_folder_is_one_plain_folder_under_users(tmp_path, name):
    with pytest.raises(ValueError):
        Desks(tmp_path).find_folder(name)


def test_nobody_can_join_as_removed():
    with pytest.raises(ValueError):
        check_username("Removed")


def test_each_name_has_one_desk_in_its_own_folder(tmp_path):
    desks = Desks(tmp_path)
    bo = desks.open("bo", NOW)
    assert desks.open("bo", NOW) is bo
    assert desks.open("cy", NOW) is not bo
    bo.todos.add("bo's", NOW)
    assert (tmp_path / "users" / "bo" / "todos.json").is_file()
    assert desks.open("cy", NOW).todos.snapshot(NOW)["open"] == []


def test_a_removed_desk_moves_aside_never_on_top_and_the_name_starts_empty(tmp_path):
    desks = Desks(tmp_path)
    desks.open("bo", NOW).todos.add("from the first bo", NOW)
    moved = desks.remove("bo", NOW)
    assert moved == tmp_path / "users" / "removed" / "bo-2026-11-16"
    assert "from the first bo" in (moved / "todos.json").read_text()
    assert not (tmp_path / "users" / "bo").exists()

    again = desks.open("bo", NOW)
    assert again.todos.snapshot(NOW)["open"] == [], "the same name starts empty"
    again.todos.add("from the second bo", NOW)
    assert desks.remove("bo", NOW) == tmp_path / "users" / "removed" / "bo-2026-11-16-2"
    assert "from the first bo" in (moved / "todos.json").read_text(), "the first one's folder is untouched"
    assert desks.remove("cy", NOW) is None, "a desk that never wrote anything has no folder to move"
