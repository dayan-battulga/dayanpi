"""Tells the dayanpi dashboard which app is in front on this Mac.

Every 2 seconds it asks macOS for the name of the frontmost app. It sends that
name to the Pi when it changes, plus a heartbeat every 60 seconds. App names are
all it ever sends: no window titles, no screenshots, nothing from inside apps.

    python3 dayanpi_mac_helper.py --once      # print the app in front and quit
    python3 dayanpi_mac_helper.py --dry-run   # keep watching, only print what it would send
    python3 dayanpi_mac_helper.py             # the real thing (DAYANPI_USER + Keychain password)

Setup and the LaunchAgent are in README.md next to this file. Standard library
only, so macOS's own /usr/bin/python3 (3.9) runs it.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from typing import Callable

DEFAULT_BASE_URL = "https://dayoon.tail279594.ts.net"
APP_ROUTE = "/api/mac/app"
KEYCHAIN_SERVICE = "dayanpi"

POLL_INTERVAL_S = 2.0
HEARTBEAT_INTERVAL_S = 60.0
FIRST_BACKOFF_S = 2.0
MAX_BACKOFF_S = 60.0
HTTP_TIMEOUT_S = 5.0
COMMAND_TIMEOUT_S = 5.0

MAX_APP_NAME_LENGTH = 100
RENAMED_APPS = {"loginwindow": "Locked"}
MAX_PROBLEM_LENGTH = 160

LSAPPINFO = "/usr/bin/lsappinfo"
OSASCRIPT = "/usr/bin/osascript"
SECURITY = "/usr/bin/security"
FRONT_APP_SCRIPT = 'tell application "System Events" to get name of first application process whose frontmost is true'
USER_AGENT = "dayanpi-mac-helper"

NO_APP_EXIT = 1
SETUP_FAILED_EXIT = 2
LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

ASN_PATTERN = re.compile(r"ASN:0x[0-9a-fA-F]+-0x[0-9a-fA-F]+:")
CLASSIC_NAME_PATTERN = re.compile(r'^\s*"LSDisplayName"\s*=\s*"(.*)"\s*$', re.MULTILINE)
RECORD_NAME_PATTERN = re.compile(r'"(.*)"\s+ASN:0x')

logger = logging.getLogger("dayanpi_mac_helper")


class SetupError(Exception):
    """Something only you can fix (no login, bad URL). The message says how."""


@dataclass
class AppDetection:
    app_name: str | None = None
    problem: str = ""


@dataclass
class SendResult:
    delivered: bool
    problem: str = ""


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]
RequestSender = Callable[[urllib.request.Request, float], int]


def run_command(args: list[str]) -> subprocess.CompletedProcess:
    """Runs a macOS tool. A missing tool or a hang comes back as exit code -1, never an exception."""
    try:
        # UTF-8 spelled out: under launchd the locale may not be, and app names like "Café" must survive.
        output = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_S,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        output = subprocess.CompletedProcess(args, -1, "", f"no answer after {COMMAND_TIMEOUT_S:.0f} s")
    except OSError as error:
        output = subprocess.CompletedProcess(args, -1, "", str(error))
    return output


def send_request(request: urllib.request.Request, timeout_s: float) -> int:
    """Sends one request and returns the HTTP status. Network trouble raises OSError."""
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
    return status


@dataclass
class HelperTools:
    """Everything that reaches outside this process, so tests can swap in fakes."""

    run: CommandRunner = run_command
    send: RequestSender = send_request
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


def parse_front_asn(text: str) -> str | None:
    """Pulls the ASN (like ASN:0x0-0x8d08d:) out of `lsappinfo front`. [ NULL ] gives None."""
    match = ASN_PATTERN.search(text)
    asn = match.group(0) if match else None
    return asn


def parse_lsappinfo_name(text: str) -> str | None:
    """Reads the app name from `lsappinfo info -only name`, in either output format."""
    # Before macOS 27 this prints "LSDisplayName"="Ghostty". macOS 27 ignores -only and
    # prints the whole record instead, whose first line is "Ghostty" ASN:0x0-0x8d08d: (in front).
    match = CLASSIC_NAME_PATTERN.search(text) or RECORD_NAME_PATTERN.match(text.lstrip())
    name = match.group(1) if match else None
    return name


def normalize_app_name(raw_name: str) -> str | None:
    """Trims the name, turns loginwindow into Locked, and keeps it within the Pi's 100 characters."""
    stripped = raw_name.strip()
    renamed = RENAMED_APPS.get(stripped, stripped)
    app_name = renamed[:MAX_APP_NAME_LENGTH].rstrip() or None
    return app_name


def summarize_output(output: subprocess.CompletedProcess) -> str:
    """One short line on what a command printed, for explaining why detection failed."""
    printed = " ".join((output.stderr.strip() or output.stdout.strip() or "nothing").split())
    summary = f"exit {output.returncode}, {printed[:MAX_PROBLEM_LENGTH]}"
    return summary


def build_detection(raw_name: str | None, problem: str) -> AppDetection:
    """Wraps a raw name. When there's no usable name, `problem` says why."""
    app_name = None if raw_name is None else normalize_app_name(raw_name)
    detection = AppDetection(app_name=app_name, problem="" if app_name else problem)
    return detection


def read_app_with_lsappinfo(run: CommandRunner) -> AppDetection:
    front = run([LSAPPINFO, "front"])
    asn = parse_front_asn(front.stdout) if front.returncode == 0 else None
    detection = AppDetection(problem=f"lsappinfo front: {summarize_output(front)}")
    if asn is not None:
        info = run([LSAPPINFO, "info", "-only", "name", asn])
        raw_name = parse_lsappinfo_name(info.stdout) if info.returncode == 0 else None
        detection = build_detection(raw_name, f"lsappinfo info: {summarize_output(info)}")
    return detection


def read_app_with_osascript(run: CommandRunner) -> AppDetection:
    output = run([OSASCRIPT, "-e", FRONT_APP_SCRIPT])
    raw_name = output.stdout if output.returncode == 0 else None
    detection = build_detection(raw_name, f"osascript: {summarize_output(output)}")
    return detection


def detect_front_app(run: CommandRunner) -> AppDetection:
    """lsappinfo first (needs no permission), osascript as the fallback."""
    detection = read_app_with_lsappinfo(run)
    if detection.app_name is None:
        fallback = read_app_with_osascript(run)
        if fallback.app_name is None:
            fallback = AppDetection(problem=f"{detection.problem}; {fallback.problem}")
        detection = fallback
    return detection


def read_keychain_password(run: CommandRunner, user: str) -> str:
    """Reads the dashboard password from the login Keychain. Raises SetupError when it isn't there."""
    output = run([SECURITY, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", user, "-w"])
    # `security -w` prints a password with any non-ASCII character as hex, so such a password can't log in.
    password = output.stdout.removesuffix("\n")
    if output.returncode != 0 or not password:
        raise SetupError(
            f"No dashboard password in the Keychain for account {user!r} "
            f"({output.stderr.strip() or 'security found nothing'}). "
            f"Add it with: security add-generic-password -s {KEYCHAIN_SERVICE} -a {user} -w"
        )
    return password


def read_app_url() -> str:
    """DAYANPI_URL (or the Tailscale default) plus /api/mac/app."""
    base_url = os.environ.get("DAYANPI_URL", "").strip() or DEFAULT_BASE_URL
    if not base_url.startswith(("https://", "http://")):
        raise SetupError(f"DAYANPI_URL should look like {DEFAULT_BASE_URL}, but it's {base_url!r}.")
    app_url = base_url.rstrip("/") + APP_ROUTE
    return app_url


def read_user() -> str:
    user = os.environ.get("DAYANPI_USER", "").strip()
    if not user:
        raise SetupError(
            "DAYANPI_USER isn't set. It's your dashboard login name: run "
            "`DAYANPI_USER=yourname python3 dayanpi_mac_helper.py` (the LaunchAgent plist sets it for you)."
        )
    return user


def encode_app(app_name: str) -> bytes:
    body = json.dumps({"app": app_name}).encode("utf-8")
    return body


def describe_status(status: int, user: str) -> SendResult:
    """Turns the Pi's HTTP status into a SendResult with a readable problem."""
    result = SendResult(delivered=200 <= status < 300)
    if status == HTTPStatus.UNAUTHORIZED:
        result.problem = (
            f"the Pi said 401, wrong login for {user!r}. Check DAYANPI_USER and the Keychain password "
            f"(security add-generic-password -U -s {KEYCHAIN_SERVICE} -a {user} -w)"
        )
    elif status == HTTPStatus.TOO_MANY_REQUESTS:
        result.problem = "the Pi said 429, too many requests"
    elif not result.delivered:
        result.problem = f"the Pi answered HTTP {status}"
    return result


class PiClient:
    """Posts the front app to the dashboard, logging in like the browser does (Basic Auth)."""

    def __init__(self, app_url: str, user: str, run: CommandRunner, send: RequestSender) -> None:
        self.app_url = app_url
        self.user = user
        self.run = run
        self.send = send
        self.password: str | None = None

    def load_password(self) -> None:
        self.password = read_keychain_password(self.run, self.user)

    def build_request(self, app_name: str) -> urllib.request.Request:
        token = base64.b64encode(f"{self.user}:{self.password}".encode("utf-8")).decode("ascii")
        request = urllib.request.Request(
            self.app_url,
            data=encode_app(app_name),
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        # urllib copies ordinary headers onto a redirect, even to another host; this one stays behind.
        request.add_unredirected_header("Authorization", f"Basic {token}")
        return request

    def send_app(self, app_name: str) -> SendResult:
        """One POST. After a 401 the Keychain is read again on the next try, so fixing it there is enough."""
        status = 0
        try:
            if self.password is None:
                self.load_password()
            status = self.send(self.build_request(app_name), HTTP_TIMEOUT_S)
            result = describe_status(status, self.user)
        except SetupError as error:
            result = SendResult(delivered=False, problem=str(error))
        except (OSError, http.client.HTTPException) as error:
            result = SendResult(
                delivered=False,
                problem=f"can't reach the Pi ({error}). Is Tailscale connected and the dayanpi service running?",
            )
        if status == HTTPStatus.UNAUTHORIZED:
            self.password = None
        return result


class AppReporter:
    """Sends the front app whenever it changes, plus a heartbeat. Failed sends back off, and only the
    newest app is ever retried, so nothing piles up while the Pi is out of reach."""

    def __init__(self, deliver: Callable[[str], SendResult], clock: Callable[[], float]) -> None:
        self.deliver = deliver
        self.clock = clock
        self.seen_app: str | None = None
        self.sent_app: str | None = None
        self.sent_at = 0.0
        self.retry_at = 0.0
        self.backoff_s = 0.0
        self.failures = 0

    def report(self, app_name: str) -> None:
        now = self.clock()
        if app_name != self.seen_app:
            logger.info("front app: %s", app_name)
            self.seen_app = app_name
        changed = app_name != self.sent_app
        heartbeat_due = now - self.sent_at >= HEARTBEAT_INTERVAL_S
        if (changed or heartbeat_due) and now >= self.retry_at:
            self.send(app_name, now)

    def send(self, app_name: str, now: float) -> None:
        result = self.deliver(app_name)
        if result.delivered:
            if self.failures:
                logger.info("reached the Pi again after %d failed tries", self.failures)
            self.sent_app = app_name
            self.sent_at = now
            self.failures = 0
            self.backoff_s = 0.0
            self.retry_at = 0.0
        else:
            self.failures += 1
            self.backoff_s = min(max(self.backoff_s * 2, FIRST_BACKOFF_S), MAX_BACKOFF_S)
            self.retry_at = now + self.backoff_s
            logger.warning(
                "couldn't send %r, trying again in %.0f s: %s", app_name, self.backoff_s, result.problem
            )


def watch_front_app(tools: HelperTools, reporter: AppReporter) -> None:
    """Checks the front app every POLL_INTERVAL_S until Ctrl+C or launchd stops it."""
    detection_failing = False
    while True:
        started = tools.clock()
        detection = detect_front_app(tools.run)
        if detection.app_name is None:
            if not detection_failing:
                logger.warning(
                    "can't tell which app is in front, skipping until that works again (%s)", detection.problem
                )
            detection_failing = True
        else:
            if detection_failing:
                logger.info("can tell which app is in front again")
            detection_failing = False
            reporter.report(detection.app_name)
        tools.sleep(max(0.0, POLL_INTERVAL_S - (tools.clock() - started)))


def show_front_app(run: CommandRunner) -> int:
    """--once: print the app in front right now. No network, no login."""
    detection = detect_front_app(run)
    exit_code = 0
    if detection.app_name is None:
        print(f"Couldn't tell which app is in front. {detection.problem}", file=sys.stderr)
        exit_code = NO_APP_EXIT
    else:
        print(detection.app_name)
    return exit_code


def run_dry_run(tools: HelperTools) -> None:
    app_url = read_app_url()
    logger.info("dry run: nothing gets sent. Switch apps to see what would go to the Pi (Ctrl+C stops).")

    def pretend_to_send(app_name: str) -> SendResult:
        logger.info("dry run, would POST %s to %s", encode_app(app_name).decode("utf-8"), app_url)
        result = SendResult(delivered=True)
        return result

    watch_front_app(tools, AppReporter(pretend_to_send, tools.clock))


def run_for_real(tools: HelperTools) -> None:
    app_url = read_app_url()
    user = read_user()
    client = PiClient(app_url, user, tools.run, tools.send)
    client.load_password()
    logger.info("sending the front app to %s as %s", app_url, user)
    watch_front_app(tools, AppReporter(client.send_app, tools.clock))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tell the dayanpi dashboard which Mac app is in front.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="print the app in front and quit (no network, no login)")
    mode.add_argument("--dry-run", action="store_true", help="keep watching, but only print what it would send")
    args = parser.parse_args(argv)
    return args


def main(argv: list[str] | None = None, tools: HelperTools | None = None) -> int:
    args = parse_args(argv)
    helper_tools = tools if tools is not None else HelperTools()
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    exit_code = 0
    try:
        if args.once:
            exit_code = show_front_app(helper_tools.run)
        elif args.dry_run:
            run_dry_run(helper_tools)
        else:
            run_for_real(helper_tools)
    except SetupError as error:
        logger.error("%s", error)
        exit_code = SETUP_FAILED_EXIT
    except KeyboardInterrupt:
        logger.info("stopped")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
