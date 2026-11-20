import json
from datetime import datetime

import pytest

from dayanpi.focus.todos import SAVE_EVERY_S, TODOS_MAX, NotepadSetting, TodoList, TodoListFull, hide_priorities
from dayanpi.focus.tracker import MAX_STEP_S, FocusLog

NOON = datetime(2026, 11, 15, 12, 0).timestamp()
LATE = datetime(2026, 11, 15, 23, 0).timestamp()
JUST_AFTER_MIDNIGHT = datetime(2026, 11, 16, 0, 0, 1).timestamp()


def make_list(tmp_path) -> TodoList:
    todos = TodoList(tmp_path / "todos.json", FocusLog(tmp_path / "focus_log"))
    return todos


def run_checks(todos: TodoList, start: float, seconds: int, counting: bool) -> float:
    """One check a second, like the worker. Returns when the last one ran."""
    for second in range(seconds + 1):
        todos.track(counting, start + second)
    return start + seconds


def find_seconds(todos: TodoList, item_id: str, now: float) -> int:
    listed = todos.snapshot(now)
    seconds = next(item["seconds"] for item in listed["open"] + listed["done"] if item["id"] == item_id)
    return seconds


def test_checking_moves_an_item_to_done_and_unchecking_moves_it_back(tmp_path):
    todos = make_list(tmp_path)
    report = todos.add("finish the report", NOON)["id"]
    emails = todos.add("reply to emails", NOON + 1)["id"]
    assert todos.change(report, NOON + 2, done=True)
    listed = todos.snapshot(NOON + 3)
    assert [item["id"] for item in listed["open"]] == [emails]
    assert [item["id"] for item in listed["done"]] == [report]
    assert listed["done"][0]["done_at"] == NOON + 2
    assert todos.change(report, NOON + 4, done=False)
    listed = todos.snapshot(NOON + 5)
    assert [item["id"] for item in listed["open"]] == [report, emails]
    assert listed["done"] == []


def test_edit_and_delete(tmp_path):
    todos = make_list(tmp_path)
    item = todos.add("laundy", NOON)["id"]
    assert todos.change(item, NOON + 1, text="laundry")
    assert todos.snapshot(NOON + 2)["open"][0]["text"] == "laundry"
    assert todos.delete(item, NOON + 3)
    assert todos.snapshot(NOON + 4)["open"] == []
    assert not todos.change(item, NOON + 5, text="gone")
    assert not todos.delete(item, NOON + 6)


def test_only_the_current_item_collects_time_and_only_while_working(tmp_path):
    todos = make_list(tmp_path)
    report = todos.add("finish the report", NOON)["id"]
    emails = todos.add("reply to emails", NOON)["id"]
    now = run_checks(todos, NOON, 60, counting=True)
    assert find_seconds(todos, report, now) == 0, "nothing is current yet"
    todos.change(report, now, current=True)
    now = run_checks(todos, now, 60, counting=True)
    now = run_checks(todos, now, 30, counting=False)  # on the phone or away
    assert find_seconds(todos, report, now) == 60
    todos.change(emails, now, current=True)
    assert todos.snapshot(now)["current"] == emails
    now = run_checks(todos, now, 10, counting=True)
    assert find_seconds(todos, report, now) == 60
    assert find_seconds(todos, emails, now) == 10


def test_checking_the_current_item_stops_its_clock_and_keeps_its_time(tmp_path):
    todos = make_list(tmp_path)
    report = todos.add("finish the report", NOON)["id"]
    todos.change(report, NOON, current=True)
    now = run_checks(todos, NOON, 90, counting=True)
    todos.change(report, now, done=True)
    assert todos.snapshot(now)["current"] is None
    now = run_checks(todos, now + 1, 30, counting=True)
    assert find_seconds(todos, report, now) == 90
    assert todos.change(report, now, current=True)  # found, but a done item can't become current
    assert todos.snapshot(now)["current"] is None


def test_stopping_being_current_only_touches_the_current_item(tmp_path):
    todos = make_list(tmp_path)
    report = todos.add("finish the report", NOON)["id"]
    emails = todos.add("reply to emails", NOON)["id"]
    todos.change(report, NOON, current=True)
    todos.change(emails, NOON + 1, current=False)
    assert todos.snapshot(NOON + 2)["current"] == report
    todos.change(report, NOON + 3, current=False)
    assert todos.snapshot(NOON + 4)["current"] is None


def test_a_stall_or_clock_jump_adds_at_most_one_step(tmp_path):
    todos = make_list(tmp_path)
    report = todos.add("finish the report", NOON)["id"]
    todos.change(report, NOON, current=True)
    todos.track(True, NOON)
    todos.track(True, NOON + 3600)
    assert find_seconds(todos, report, NOON + 3600) == MAX_STEP_S


def test_at_midnight_only_the_days_done_items_leave(tmp_path):
    todos = make_list(tmp_path)
    report = todos.add("finish the report", NOON)["id"]
    laundry = todos.add("do laundry", NOON)["id"]
    todos.change(report, LATE, done=True)
    assert [item["id"] for item in todos.snapshot(LATE + 59 * 60)["done"]] == [report]
    todos.track(False, JUST_AFTER_MIDNIGHT)
    listed = todos.snapshot(JUST_AFTER_MIDNIGHT)
    assert listed["done"] == []
    assert [item["id"] for item in listed["open"]] == [laundry]
    saved = json.loads((tmp_path / "todos.json").read_text())
    assert [item["id"] for item in saved["items"]] == [laundry]


def test_a_restart_keeps_the_list_the_current_item_and_its_time(tmp_path):
    todos = make_list(tmp_path)
    report = todos.add("finish the report", NOON)["id"]
    todos.change(report, NOON, current=True)
    run_checks(todos, NOON, int(SAVE_EVERY_S) + 5, counting=True)
    restarted = make_list(tmp_path)
    listed = restarted.snapshot(NOON + 60)
    assert listed["current"] == report
    assert listed["open"][0]["seconds"] == pytest.approx(SAVE_EVERY_S, abs=1)
    assert list(tmp_path.glob("*.tmp")) == []


def test_an_unreadable_file_is_moved_aside_instead_of_saved_over(tmp_path):
    (tmp_path / "todos.json").write_text("{not json")
    todos = make_list(tmp_path)
    assert todos.snapshot(NOON) == {"current": None, "open": [], "done": []}
    assert (tmp_path / "todos.json.broken").read_text() == "{not json"
    todos.add("start over", NOON)
    assert (tmp_path / "todos.json.broken").read_text() == "{not json"


def test_added_current_done_and_undone_go_to_the_focus_log(tmp_path):
    todos = make_list(tmp_path)
    report = todos.add("finish the report", NOON)["id"]
    todos.change(report, NOON + 1, current=True)
    run_checks(todos, NOON + 1, 120, counting=True)
    todos.change(report, NOON + 200, done=True)
    todos.change(report, NOON + 300, done=False)
    lines = FocusLog(tmp_path / "focus_log").read_day("2026-11-15")
    todo_lines = [line for line in lines if line["event"] == "todo"]
    assert [line["action"] for line in todo_lines] == ["added", "current", "done", "current", "undone"]
    done = todo_lines[2]
    assert (done["id"], done["text"], done["seconds"]) == (report, "finish the report", 120)
    assert todo_lines[3]["id"] is None, "checking the current item clears current"


def test_a_full_list_takes_no_more_until_some_are_gone(tmp_path):
    todos = make_list(tmp_path)
    first = todos.add("first", NOON)["id"]
    todos.change(first, NOON, done=True)
    for index in range(TODOS_MAX - 1):
        todos.add(f"item {index}", NOON)
    saved = (tmp_path / "todos.json").read_text()
    with pytest.raises(TodoListFull):
        todos.add("one too many", NOON)
    assert (tmp_path / "todos.json").read_text() == saved, "nothing saved"
    assert "one too many" not in json.dumps(todos.snapshot(NOON)), "done ones count too"
    todos.delete(first, NOON)
    assert todos.add("room again", NOON)["text"] == "room again"


def test_priorities_start_as_none_change_and_survive_a_restart(tmp_path):
    todos = make_list(tmp_path)
    demo = todos.add("project demo", NOON)
    assert demo["priority"] == "none"
    assert todos.change(demo["id"], NOON + 1, priority="high")
    assert todos.snapshot(NOON + 2)["open"][0]["priority"] == "high"
    assert make_list(tmp_path).snapshot(NOON + 3)["open"][0]["priority"] == "high"


def test_to_dos_saved_before_priorities_load_as_none(tmp_path):
    (tmp_path / "todos.json").write_text(json.dumps({"current": "a", "items": [{"id": "a", "text": "old one", "created_at": NOON, "done_at": None, "seconds": 60.0}]}))
    listed = make_list(tmp_path).snapshot(NOON + 1)
    assert (listed["current"], listed["open"][0]["priority"]) == ("a", "none")


def test_someone_elses_view_of_a_list_has_no_priorities(tmp_path):
    todos = make_list(tmp_path)
    todos.change(todos.add("demo", NOON)["id"], NOON, priority="high")
    todos.change(todos.add("lab", NOON)["id"], NOON, done=True)
    hidden = hide_priorities(todos.snapshot(NOON + 1))
    assert all("priority" not in item for item in hidden["open"] + hidden["done"])
    assert [item["text"] for item in hidden["open"] + hidden["done"]] == ["demo", "lab"]


def test_the_notepad_shows_every_priority_until_one_is_switched_off(tmp_path):
    notepad = NotepadSetting(tmp_path / "notepad.json")
    assert notepad.read() == {"high": True, "medium": True, "low": True, "none": True}
    notepad.update({"low": False, "none": "no", "urgent": False})
    assert NotepadSetting(tmp_path / "notepad.json").read() == {"high": True, "medium": True, "low": False, "none": True}
