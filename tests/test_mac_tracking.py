import json
import logging

from dayanpi.focus.mac_tracking import MacTrackingSetting


def test_it_starts_on_without_a_file(tmp_path):
    setting = MacTrackingSetting(tmp_path / "mac_tracking.json")
    assert setting.enabled is True
    assert not (tmp_path / "mac_tracking.json").exists(), "nothing written until it changes"


def test_a_restart_keeps_the_last_pick(tmp_path):
    path = tmp_path / "mac_tracking.json"
    assert MacTrackingSetting(path).set(False) is True
    assert json.loads(path.read_text()) == {"enabled": False}
    restarted = MacTrackingSetting(path)
    assert restarted.enabled is False
    assert restarted.set(False) is False, "same value, no change"
    assert restarted.set(True) is True
    assert MacTrackingSetting(path).enabled is True
    assert list(tmp_path.glob("*.tmp")) == []


def test_an_unreadable_file_means_on(tmp_path, caplog):
    path = tmp_path / "mac_tracking.json"
    for broken in ("{not json", '["enabled"]', '{"enabled": "no"}'):
        path.write_text(broken)
        with caplog.at_level(logging.WARNING):
            assert MacTrackingSetting(path).enabled is True
    assert caplog.text.count("so Mac tracking is on") == 2, "a non-bool value just means on"
