import base64
import http.client
import io
import json
import logging
import plistlib
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from mac_helper import dayanpi_mac_helper as helper

HELPER_DIR = Path(helper.__file__).resolve().parent
APP_URL = helper.DEFAULT_BASE_URL + helper.APP_ROUTE
USER = "dayan"
PASSWORD = "hunter2-not-real"

FRONT_ASN = "ASN:0x0-0x8d08d:\n"
NULL_OUTPUT = "[ NULL ]\n"
CLASSIC_NAME_OUTPUT = '"LSDisplayName"="Google Chrome"\n'
# macOS 27 ignores `-only name` and prints the whole record with everything else
# blanked out (verbatim from a 27.0.1 Mac). Older versions print the line above.
MACOS27_NAME_OUTPUT = (
    '"Ghostty" ASN:0x0-0x8d08d: (in front) \n'
    "    bundleID=[ NULL ] \n"
    "    bundle path=[ NULL ] \n"
    "    executable path=[ NULL ] \n"
    " !cgsConnection !signalled type=[ NULL ]  flavor=[ NULL ]  Version=[ NULL ]  Arch=!!none \n"
)
FULL_RECORD_OUTPUT = (
    '"Moom" ASN:0x0-0x13a73a6: \n'
    '    bundleID="com.manytricks.Moom"\n'
    '    bundle path="/Applications/Moom.app"\n'
    '    executable path="/Applications/Moom.app/Contents/MacOS/Moom"\n'
    '    pid = 89861 type="UIElement" flavor=3 Version="3181" fileType="APPL" creator="????" Arch=x86_64 \n'
    '    parentASN="loginwindow" ASN:0x0-0x1394393: \n'
)
OSASCRIPT_DENIED = "0:91: execution error: Not authorized to send Apple events to System Events. (-1743)\n"
KEYCHAIN_MISSING = "security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain.\n"


class LoopStopped(Exception):
    """Raised by FakeClock to end the helper's endless loop."""


class FakeMac:
    """Answers like lsappinfo, osascript and security would. None in front_apps means nothing is in front."""

    def __init__(self, front_apps=("Code",), lsappinfo_works=True, osascript_app=None, password=PASSWORD):
        self.front_apps = list(front_apps)
        self.lsappinfo_works = lsappinfo_works
        self.osascript_app = osascript_app
        self.password = password
        self.current_app = None
        self.commands = []

    def run(self, args):
        self.commands.append(list(args))
        tool = Path(args[0]).name
        if tool == "security":
            output = self.answer_security()
        elif tool == "osascript":
            output = self.answer_osascript()
        elif args[1] == "front":
            output = self.answer_front()
        else:
            output = helper.CommandOutput(0, f'"LSDisplayName"="{self.current_app}"\n', "")
        return output

    def answer_front(self):
        self.current_app = self.front_apps.pop(0) if len(self.front_apps) > 1 else self.front_apps[0]
        output = helper.CommandOutput(0, NULL_OUTPUT if self.current_app is None else FRONT_ASN, "")
        if not self.lsappinfo_works:
            output = helper.CommandOutput(-1, "", "[Errno 2] No such file or directory: '/usr/bin/lsappinfo'")
        return output

    def answer_osascript(self):
        output = helper.CommandOutput(1, "", OSASCRIPT_DENIED)
        if self.osascript_app is not None:
            output = helper.CommandOutput(0, f"{self.osascript_app}\n", "")
        return output

    def answer_security(self):
        output = helper.CommandOutput(44, "", KEYCHAIN_MISSING)
        if self.password is not None:
            output = helper.CommandOutput(0, f"{self.password}\n", "")
        return output

    def count_runs(self, tool):
        runs = sum(Path(args[0]).name == tool for args in self.commands)
        return runs


class FakePi:
    """Records every request and answers with the scripted statuses or errors, repeating the last one."""

    def __init__(self, answers=(200,)):
        self.answers = list(answers)
        self.requests = []
        self.timeouts = []

    def send(self, request, timeout_s):
        self.requests.append(request)
        self.timeouts.append(timeout_s)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def read_sent_apps(self):
        sent_apps = [json.loads(request.data)["app"] for request in self.requests]
        return sent_apps


class FakeClock:
    """time.monotonic and time.sleep in one. Sleeping moves the clock, and the Nth sleep ends the loop."""

    def __init__(self, stop_after_sleeps=None, stop_with=LoopStopped):
        self.now = 1000.0
        self.stop_after_sleeps = stop_after_sleeps
        self.stop_with = stop_with
        self.sleep_count = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleep_count += 1
        if self.sleep_count == self.stop_after_sleeps:
            raise self.stop_with()
        self.now += seconds


class FakeDelivery:
    """Stands in for PiClient.send_app: records each attempt and answers with scripted outcomes."""

    def __init__(self, clock, outcomes=(True,)):
        self.clock = clock
        self.outcomes = list(outcomes)
        self.attempted_apps = []
        self.attempt_times = []

    def send_app(self, app_name):
        self.attempted_apps.append(app_name)
        self.attempt_times.append(self.clock())
        delivered = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        result = helper.SendResult(delivered=delivered, problem="" if delivered else "Pi unplugged")
        return result


class FakeResponse:
    def __init__(self, status):
        self.status = status
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True


@pytest.fixture(autouse=True)
def mac_environment(monkeypatch):
    monkeypatch.setenv("DAYANPI_USER", USER)
    monkeypatch.delenv("DAYANPI_URL", raising=False)


def make_tools(mac, pi, clock):
    tools = helper.HelperTools(run=mac.run, send=pi.send, clock=clock, sleep=clock.sleep)
    return tools


def make_auth_header(password):
    header = "Basic " + base64.b64encode(f"{USER}:{password}".encode()).decode()
    return header


def run_until_stopped(argv, mac, pi, clock):
    with pytest.raises(LoopStopped):
        helper.main(argv, make_tools(mac, pi, clock))


def report_every(reporter, clock, apps, seconds):
    for app in apps:
        reporter.report(app)
        clock.now += seconds



def test_front_asn_is_read_from_lsappinfo_front():
    assert helper.parse_front_asn(FRONT_ASN) == "ASN:0x0-0x8d08d:"


@pytest.mark.parametrize("output", [NULL_OUTPUT, "", "\n", "ASN:\n", "lsappinfo: connection invalid\n"])
def test_front_asn_is_none_when_nothing_usable_comes_back(output):
    assert helper.parse_front_asn(output) is None


@pytest.mark.parametrize(
    "output, expected",
    [
        (CLASSIC_NAME_OUTPUT, "Google Chrome"),
        (MACOS27_NAME_OUTPUT, "Ghostty"),
        (FULL_RECORD_OUTPUT, "Moom"),
        ('"LSDisplayName"="Microsoft Word"', "Microsoft Word"),
    ],
)
def test_lsappinfo_name_is_read_from_every_format(output, expected):
    assert helper.parse_lsappinfo_name(output) == expected


@pytest.mark.parametrize(
    "output", [NULL_OUTPUT, "", "\n\n", '"LSDisplayName"=[ NULL ]\n', "    bundleID=[ NULL ] \n", "garbage\n"]
)
def test_lsappinfo_name_is_none_for_null_or_junk(output):
    assert helper.parse_lsappinfo_name(output) is None


@pytest.mark.parametrize(
    "raw_name, expected",
    [("  Slack \n", "Slack"), ("loginwindow", "Locked"), ("x" * 150, "x" * 100), ("", None), (" \n", None)],
)
def test_app_names_are_trimmed_renamed_and_capped(raw_name, expected):
    assert helper.normalize_app_name(raw_name) == expected



def test_detection_asks_lsappinfo_first():
    mac = FakeMac(front_apps=["Google Chrome"])
    detection = helper.detect_front_app(mac.run)
    assert detection.app_name == "Google Chrome"
    assert mac.commands == [
        ["/usr/bin/lsappinfo", "front"],
        ["/usr/bin/lsappinfo", "info", "-only", "name", "ASN:0x0-0x8d08d:"],
    ]


def test_detection_falls_back_to_osascript():
    mac = FakeMac(lsappinfo_works=False, osascript_app="Code")
    detection = helper.detect_front_app(mac.run)
    assert detection.app_name == "Code"
    assert mac.commands[-1] == ["/usr/bin/osascript", "-e", helper.FRONT_APP_SCRIPT]


def test_detection_explains_when_both_ways_fail():
    detection = helper.detect_front_app(FakeMac(front_apps=[None]).run)
    assert detection.app_name is None
    assert "lsappinfo front: exit 0, [ NULL ]" in detection.problem
    assert "(-1743)" in detection.problem


def test_detection_treats_a_blank_osascript_answer_as_a_miss():
    detection = helper.detect_front_app(FakeMac(lsappinfo_works=False, osascript_app="").run)
    assert detection.app_name is None
    assert "osascript: exit 0, nothing" in detection.problem


def test_locked_screen_shows_up_as_locked():
    detection = helper.detect_front_app(FakeMac(front_apps=["loginwindow"]).run)
    assert detection.app_name == "Locked"



def test_sends_changes_right_away_and_a_heartbeat_every_minute():
    clock = FakeClock()
    delivery = FakeDelivery(clock)
    reporter = helper.AppReporter(delivery.send_app, clock)
    timeline = {0: "Code", 2: "Code", 59: "Code", 60: "Code", 62: "Slack", 121: "Slack", 122: "Slack"}
    for offset, app in timeline.items():
        clock.now = 1000.0 + offset
        reporter.report(app)
    assert delivery.attempted_apps == ["Code", "Code", "Slack", "Slack"]
    assert delivery.attempt_times == [1000.0, 1060.0, 1062.0, 1122.0]


def test_failed_sends_back_off_doubling_up_to_a_minute():
    clock = FakeClock()
    delivery = FakeDelivery(clock, outcomes=[False])
    reporter = helper.AppReporter(delivery.send_app, clock)
    report_every(reporter, clock, ["Code"] * 300, helper.POLL_INTERVAL_S)
    times = delivery.attempt_times
    gaps = [later - earlier for earlier, later in zip(times, times[1:])]
    assert gaps[:8] == [2, 4, 8, 16, 32, 60, 60, 60]
    assert max(gaps) == helper.MAX_BACKOFF_S


def test_backoff_resets_once_the_pi_answers(caplog):
    caplog.set_level(logging.INFO)
    clock = FakeClock()
    delivery = FakeDelivery(clock, outcomes=[False, False, False, True])
    reporter = helper.AppReporter(delivery.send_app, clock)
    report_every(reporter, clock, ["Code"] * 20 + ["Slack"], helper.POLL_INTERVAL_S)
    assert delivery.attempted_apps == ["Code", "Code", "Code", "Code", "Slack"]
    assert delivery.attempt_times[-1] == 1040.0
    assert "reached the Pi again after 3 failed tries" in caplog.text


def test_only_the_newest_app_is_retried():
    clock = FakeClock()
    delivery = FakeDelivery(clock, outcomes=[False, False, True])
    reporter = helper.AppReporter(delivery.send_app, clock)
    report_every(reporter, clock, ["Code", "Code", "Slack", "Notion"], helper.POLL_INTERVAL_S)
    assert delivery.attempted_apps == ["Code", "Code", "Notion"]


def test_a_long_outage_never_overflows_the_backoff():
    clock = FakeClock()
    delivery = FakeDelivery(clock, outcomes=[False])
    reporter = helper.AppReporter(delivery.send_app, clock)
    report_every(reporter, clock, ["Code"] * 2000, helper.MAX_BACKOFF_S)
    assert len(delivery.attempted_apps) == 2000
    assert reporter.backoff_s == helper.MAX_BACKOFF_S



def test_client_posts_the_app_as_json_with_basic_auth():
    mac = FakeMac()
    pi = FakePi()
    result = helper.PiClient(APP_URL, USER, mac.run, pi.send).send_app("Code")
    request = pi.requests[0]
    assert result.delivered
    assert request.full_url == "https://dayoon.tail279594.ts.net/api/mac/app"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"app": "Code"}
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Authorization") == make_auth_header(PASSWORD)
    assert pi.timeouts == [5.0]
    assert mac.commands == [["/usr/bin/security", "find-generic-password", "-s", "dayanpi", "-a", USER, "-w"]]


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided, or not known")),
        socket.timeout("timed out"),
        ConnectionResetError(54, "Connection reset by peer"),
        http.client.RemoteDisconnected("Remote end closed connection without response"),
    ],
)
def test_client_turns_network_errors_into_a_failed_send(error):
    result = helper.PiClient(APP_URL, USER, FakeMac().run, FakePi([error]).send).send_app("Code")
    assert not result.delivered
    assert "can't reach the Pi" in result.problem


def test_client_rereads_the_keychain_after_a_401():
    mac = FakeMac()
    pi = FakePi([401, 200])
    client = helper.PiClient(APP_URL, USER, mac.run, pi.send)
    rejected = client.send_app("Code")
    mac.password = "fixed-password"
    accepted = client.send_app("Code")
    assert not rejected.delivered
    assert "401" in rejected.problem
    assert "security add-generic-password -U -s dayanpi -a dayan -w" in rejected.problem
    assert accepted.delivered
    assert pi.requests[1].get_header("Authorization") == make_auth_header("fixed-password")
    assert mac.count_runs("security") == 2


def test_client_survives_the_keychain_entry_vanishing_mid_run():
    mac = FakeMac()
    pi = FakePi([401])
    client = helper.PiClient(APP_URL, USER, mac.run, pi.send)
    client.send_app("Code")
    mac.password = None
    result = client.send_app("Code")
    assert not result.delivered
    assert "security add-generic-password -s dayanpi -a dayan -w" in result.problem
    assert len(pi.requests) == 1


@pytest.mark.parametrize("status, hint", [(422, "HTTP 422"), (429, "too many requests"), (500, "HTTP 500")])
def test_client_names_other_refusals(status, hint):
    result = helper.PiClient(APP_URL, USER, FakeMac().run, FakePi([status]).send).send_app("Code")
    assert not result.delivered
    assert hint in result.problem



def test_live_run_sends_changes_and_heartbeats():
    pi = FakePi()
    run_until_stopped([], FakeMac(front_apps=["Code"] * 10 + ["Slack"]), pi, FakeClock(stop_after_sleeps=50))
    assert pi.read_sent_apps() == ["Code", "Slack", "Slack"]
    assert {request.full_url for request in pi.requests} == {APP_URL}


def test_live_run_rides_out_network_errors_and_catches_up(caplog):
    caplog.set_level(logging.INFO)
    pi = FakePi([urllib.error.URLError("no route to host"), urllib.error.URLError("timed out"), 200])
    run_until_stopped([], FakeMac(front_apps=["Code"] * 3 + ["Slack"]), pi, FakeClock(stop_after_sleeps=10))
    assert pi.read_sent_apps() == ["Code", "Code", "Slack"]
    assert "can't reach the Pi" in caplog.text
    assert "reached the Pi again after 2 failed tries" in caplog.text


def test_live_run_keeps_going_through_401s(caplog):
    mac = FakeMac()
    pi = FakePi([401])
    run_until_stopped([], mac, pi, FakeClock(stop_after_sleeps=60))
    assert len(pi.requests) == 6
    assert caplog.text.count("the Pi said 401, wrong login for 'dayan'") == 6
    assert mac.count_runs("security") == 6


def test_password_never_shows_up_in_the_output(caplog, capsys):
    caplog.set_level(logging.DEBUG)
    mac = FakeMac(front_apps=["Code", "Slack", "Notion"])
    pi = FakePi([200, 401, urllib.error.URLError("no route to host"), 500, 200])
    run_until_stopped([], mac, pi, FakeClock(stop_after_sleeps=20))
    captured = capsys.readouterr()
    everything = caplog.text + captured.out + captured.err
    assert len(pi.requests) == 5
    assert PASSWORD not in everything
    assert make_auth_header(PASSWORD).split()[1] not in everything


def test_detection_trouble_is_logged_once_not_every_tick(caplog):
    caplog.set_level(logging.INFO)
    pi = FakePi()
    run_until_stopped([], FakeMac(front_apps=[None, None, None, "Code"]), pi, FakeClock(stop_after_sleeps=6))
    assert caplog.text.count("can't tell which app is in front") == 1
    assert caplog.text.count("can tell which app is in front again") == 1
    assert pi.read_sent_apps() == ["Code"]


def test_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv("DAYANPI_URL", "http://127.0.0.1:8000/")
    pi = FakePi()
    run_until_stopped([], FakeMac(), pi, FakeClock(stop_after_sleeps=1))
    assert pi.requests[0].full_url == "http://127.0.0.1:8000/api/mac/app"


def test_ctrl_c_exits_quietly():
    clock = FakeClock(stop_after_sleeps=1, stop_with=KeyboardInterrupt)
    assert helper.main([], make_tools(FakeMac(), FakePi(), clock)) == 0



def test_missing_user_stops_with_a_clear_message(monkeypatch, caplog):
    monkeypatch.delenv("DAYANPI_USER")
    mac = FakeMac()
    pi = FakePi()
    assert helper.main([], make_tools(mac, pi, FakeClock())) == helper.SETUP_FAILED_EXIT
    assert "DAYANPI_USER isn't set" in caplog.text
    assert mac.commands == []
    assert pi.requests == []


def test_missing_keychain_password_stops_with_the_fix(caplog):
    pi = FakePi()
    assert helper.main([], make_tools(FakeMac(password=None), pi, FakeClock())) == helper.SETUP_FAILED_EXIT
    assert "could not be found in the keychain" in caplog.text
    assert "security add-generic-password -s dayanpi -a dayan -w" in caplog.text
    assert pi.requests == []


def test_url_without_a_scheme_stops_with_a_clear_message(monkeypatch, caplog):
    monkeypatch.setenv("DAYANPI_URL", "dayoon.tail279594.ts.net")
    assert helper.main([], make_tools(FakeMac(), FakePi(), FakeClock())) == helper.SETUP_FAILED_EXIT
    assert "DAYANPI_URL should look like https://dayoon.tail279594.ts.net" in caplog.text



def test_once_prints_the_app_without_login_or_network(monkeypatch, capsys):
    monkeypatch.delenv("DAYANPI_USER")
    mac = FakeMac(front_apps=["Google Chrome"])
    pi = FakePi()
    assert helper.main(["--once"], make_tools(mac, pi, FakeClock())) == 0
    assert capsys.readouterr().out == "Google Chrome\n"
    assert pi.requests == []
    assert mac.count_runs("security") == 0


def test_once_explains_when_it_cannot_tell(capsys):
    exit_code = helper.main(["--once"], make_tools(FakeMac(front_apps=[None]), FakePi(), FakeClock()))
    captured = capsys.readouterr()
    assert exit_code == helper.NO_APP_EXIT
    assert captured.out == ""
    assert "Not authorized to send Apple events" in captured.err


def test_dry_run_prints_what_it_would_send_and_sends_nothing(monkeypatch, caplog):
    monkeypatch.delenv("DAYANPI_USER")
    caplog.set_level(logging.INFO)
    mac = FakeMac(front_apps=["Code"] * 5 + ["Slack"])
    pi = FakePi()
    run_until_stopped(["--dry-run"], mac, pi, FakeClock(stop_after_sleeps=40))
    would_send = [message for message in caplog.messages if message.startswith("dry run, would POST")]
    assert would_send == [
        f'dry run, would POST {{"app": "Code"}} to {APP_URL}',
        f'dry run, would POST {{"app": "Slack"}} to {APP_URL}',
        f'dry run, would POST {{"app": "Slack"}} to {APP_URL}',
    ]
    assert pi.requests == []
    assert mac.count_runs("security") == 0



def test_run_command_turns_a_missing_tool_into_a_failed_exit(monkeypatch):
    def refuse(args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", args[0])

    monkeypatch.setattr(subprocess, "run", refuse)
    output = helper.run_command(["/usr/bin/lsappinfo", "front"])
    assert output.exit_code == -1
    assert "No such file or directory" in output.stderr


def test_run_command_gives_up_on_a_hung_tool(monkeypatch):
    def hang(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    output = helper.run_command(["/usr/bin/osascript", "-e", helper.FRONT_APP_SCRIPT])
    assert output.exit_code == -1
    assert output.stderr == "no answer after 5 s"


def test_run_command_decodes_what_the_tool_printed(monkeypatch):
    def answer(args, **kwargs):
        completed = subprocess.CompletedProcess(args, 0, stdout="Café\n".encode(), stderr=b"")
        return completed

    monkeypatch.setattr(subprocess, "run", answer)
    assert helper.run_command(["/usr/bin/osascript"]) == helper.CommandOutput(0, "Café\n", "")


def test_send_request_returns_the_status_and_closes_the_response(monkeypatch):
    response = FakeResponse(200)
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: response)
    assert helper.send_request(urllib.request.Request(APP_URL), 5.0) == 200
    assert response.closed


def test_send_request_turns_http_errors_into_their_status(monkeypatch):
    def reject(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"Unauthorized"))

    monkeypatch.setattr(urllib.request, "urlopen", reject)
    assert helper.send_request(urllib.request.Request(APP_URL), 5.0) == 401



def test_launch_agent_template_runs_this_script():
    with open(HELPER_DIR / "com.dayanpi.machelper.plist", "rb") as plist_file:
        agent = plistlib.load(plist_file)
    assert agent["Label"] == "com.dayanpi.machelper"
    assert agent["ProgramArguments"] == ["/usr/bin/python3", "__HOME__/dayanpi-mac-helper/dayanpi_mac_helper.py"]
    assert Path(helper.__file__).name == "dayanpi_mac_helper.py"
    assert agent["RunAtLoad"] is True
    assert agent["KeepAlive"] is True
    assert agent["EnvironmentVariables"] == {"DAYANPI_USER": "__DAYANPI_USER__", "DAYANPI_URL": "__DAYANPI_URL__"}
    assert agent["StandardOutPath"] == "__HOME__/Library/Logs/dayanpi-mac-helper.log"
    assert agent["StandardErrorPath"] == agent["StandardOutPath"]
