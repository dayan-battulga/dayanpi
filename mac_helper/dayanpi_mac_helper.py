"""Tells the dayanpi dashboard which app is in front on this Mac.

Every 2 seconds it asks macOS for the name of the frontmost app, and when that's a
browser it can ask (Chrome, Brave, Edge, Arc), the site of the active tab: just the
host name without www., like youtube.com. It sends both to the Pi when either changes,
plus a heartbeat every 60 seconds. Never a full URL, a path, a query or a page title,
and nothing at all from incognito/private windows. Safari and Firefox send no site:
Safari can't tell a script which windows are private, and Firefox has no tabs to ask.

The dashboard has a switch for it. The helper asks the Pi every 10 seconds (and reads the
answer off every report too); while it's off, it doesn't look at the front app or any
browser at all, and when it comes back on it sends the app in front right away.

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
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from typing import Callable

DEFAULT_BASE_URL = "https://dayoon.tail279594.ts.net"
APP_ROUTE = "/api/mac/app"
TRACKING_ROUTE = "/api/mac/tracking"
KEYCHAIN_SERVICE = "dayanpi"

POLL_INTERVAL_S = 2.0
HEARTBEAT_INTERVAL_S = 60.0
FIRST_BACKOFF_S = 2.0
MAX_BACKOFF_S = 60.0
HTTP_TIMEOUT_S = 5.0
TRACKING_CHECK_S = 10.0  # how often it asks the Pi whether the dashboard's switch is on
MAX_REPLY_BYTES = 4096
COMMAND_TIMEOUT_S = 5.0

MAX_APP_NAME_LENGTH = 100
RENAMED_APPS = {"loginwindow": "Locked"}
MAX_PROBLEM_LENGTH = 160

LSAPPINFO = "/usr/bin/lsappinfo"
OSASCRIPT = "/usr/bin/osascript"
SECURITY = "/usr/bin/security"
FRONT_APP_SCRIPT = 'tell application "System Events" to get name of first application process whose frontmost is true'
# Each prints the active tab's URL, or nothing for a private window, no window, or a browser that just quit
# ("is running" first, so the script can't start it again). Anything they can't confirm is a normal window
# fails closed: no site.
CHROMIUM_URL_SCRIPT = """
if application "{app}" is running then
    tell application "{app}"
        if (count of windows) > 0 and mode of front window is "normal" then return URL of active tab of front window
    end tell
end if
return ""
"""
ARC_URL_SCRIPT = """
if application "Arc" is running then
    tell application "Arc"
        if (count of windows) > 0 and not (incognito of front window) then return URL of active tab of front window
    end tell
end if
return ""
"""
BROWSER_URL_SCRIPTS = {
    "Google Chrome": CHROMIUM_URL_SCRIPT.format(app="Google Chrome"),
    "Brave Browser": CHROMIUM_URL_SCRIPT.format(app="Brave Browser"),
    "Microsoft Edge": CHROMIUM_URL_SCRIPT.format(app="Microsoft Edge"),
    "Arc": ARC_URL_SCRIPT,
}
UNREADABLE_BROWSERS = {
    "Safari": "Safari can't tell a script which windows are private",
    "Firefox": "Firefox has no AppleScript for its tabs",
}
WEB_SCHEMES = ("http", "https")
MAX_SITE_LENGTH = 253
# A plain host name, the same check the Pi makes: lowercase labels of letters, digits and inner hyphens.
SITE_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
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
class SiteDetection:
    site: str | None = None
    problem: str = ""  # why a browser gave no site (not private windows: those are just no site)


@dataclass
class SendResult:
    delivered: bool
    problem: str = ""
    enabled: bool | None = None  # the dashboard's switch, when the reply said


@dataclass
class Reply:
    status: int
    body: bytes = b""


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]
RequestSender = Callable[[urllib.request.Request, float], Reply]


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


def send_request(request: urllib.request.Request, timeout_s: float) -> Reply:
    """Sends one request and returns the HTTP status and the start of the body. Network trouble raises OSError."""
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            reply = Reply(status=response.status, body=response.read(MAX_REPLY_BYTES))
    except urllib.error.HTTPError as error:
        reply = Reply(status=error.code)
        error.close()
    return reply


def read_enabled(body: bytes) -> bool | None:
    """The "enabled" in a reply from the Pi, or None when it doesn't say (an older Pi, an error page)."""
    try:
        enabled = json.loads(body or b"{}").get("enabled")
    except (ValueError, AttributeError):
        enabled = None
    switch = enabled if isinstance(enabled, bool) else None
    return switch


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


def find_site(url: str) -> str | None:
    """The host name of a web page's URL without www., like youtube.com. None for anything that isn't an
    http(s) page with a plain host name: file://, chrome://, about:blank, an empty tab, an IP v6 address."""
    try:
        parts = urllib.parse.urlsplit(url.strip())
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").removeprefix("www.")
        scheme = parts.scheme
    except (ValueError, UnicodeError):
        host = scheme = ""
    is_site = scheme in WEB_SCHEMES and len(host) <= MAX_SITE_LENGTH and SITE_PATTERN.match(host) is not None
    site = host if is_site else None
    return site


def detect_site(run: CommandRunner, app_name: str) -> SiteDetection:
    """Asks the browser in front for its active tab's URL and keeps only the site. Other apps have no site."""
    script = BROWSER_URL_SCRIPTS.get(app_name)
    detection = SiteDetection(problem=UNREADABLE_BROWSERS.get(app_name, ""))
    if script is not None:
        output = run([OSASCRIPT, "-e", script])
        problem = "" if output.returncode == 0 else f"osascript: {summarize_output(output)}"
        detection = SiteDetection(site=find_site(output.stdout) if output.returncode == 0 else None, problem=problem)
    return detection


def describe_front(app_name: str, site: str | None) -> str:
    text = app_name if site is None else f"{app_name} · {site}"
    return text


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


def encode_app(app_name: str, site: str | None = None) -> bytes:
    body = json.dumps({"app": app_name, "site": site}).encode("utf-8")
    return body


def describe_status(status: int, user: str) -> SendResult:
    """Turns the Pi's HTTP status into a SendResult with a readable problem."""
    result = SendResult(delivered=200 <= status < 300)
    if status == HTTPStatus.UNAUTHORIZED:
        result.problem = (
            f"the Pi said 401, wrong login for {user!r}. Check DAYANPI_USER and the Keychain password "
            f"(security add-generic-password -U -s {KEYCHAIN_SERVICE} -a {user} -w)"
        )
    elif not result.delivered:
        result.problem = f"the Pi answered HTTP {status}"
    return result


class PiClient:
    """Posts the front app to the dashboard and asks about its switch, logging in like the browser does (Basic Auth)."""

    def __init__(self, app_url: str, user: str, run: CommandRunner, send: RequestSender) -> None:
        self.app_url = app_url
        self.tracking_url = app_url[: -len(APP_ROUTE)] + TRACKING_ROUTE
        self.user = user
        self.run = run
        self.send = send
        self.password: str | None = None

    def load_password(self) -> None:
        self.password = read_keychain_password(self.run, self.user)

    def build_request(self, app_name: str, site: str | None = None) -> urllib.request.Request:
        request = urllib.request.Request(
            self.app_url,
            data=encode_app(app_name, site),
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        self.add_login(request)
        return request

    def add_login(self, request: urllib.request.Request) -> None:
        token = base64.b64encode(f"{self.user}:{self.password}".encode("utf-8")).decode("ascii")
        # urllib copies ordinary headers onto a redirect, even to another host; this one stays behind.
        request.add_unredirected_header("Authorization", f"Basic {token}")

    def read_tracking(self) -> bool | None:
        """GET the dashboard's switch: True or False, or None when the Pi can't say (out of reach, wrong login)."""
        status = 0
        enabled = None
        try:
            if self.password is None:
                self.load_password()
            request = urllib.request.Request(self.tracking_url, method="GET", headers={"User-Agent": USER_AGENT})
            self.add_login(request)
            reply = self.send(request, HTTP_TIMEOUT_S)
            status = reply.status
            enabled = read_enabled(reply.body) if 200 <= status < 300 else None
        except (SetupError, OSError, http.client.HTTPException):
            enabled = None
        if status == HTTPStatus.UNAUTHORIZED:
            self.password = None
        return enabled

    def send_app(self, app_name: str, site: str | None = None) -> SendResult:
        """One POST. After a 401 the Keychain is read again on the next try, so fixing it there is enough."""
        status = 0
        try:
            if self.password is None:
                self.load_password()
            reply = self.send(self.build_request(app_name, site), HTTP_TIMEOUT_S)
            status = reply.status
            result = describe_status(status, self.user)
            result.enabled = read_enabled(reply.body) if result.delivered else None
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
    """Sends the front app and site whenever either changes, plus a heartbeat. Failed sends back off, and
    only the newest app is ever retried, so nothing piles up while the Pi is out of reach."""

    def __init__(self, deliver: Callable[[str, str | None], SendResult], clock: Callable[[], float]) -> None:
        self.deliver = deliver
        self.clock = clock
        self.seen_front: str | None = None  # "app · site", what the log last said
        self.sent_front: str | None = None
        self.sent_at = 0.0
        self.retry_at = 0.0
        self.backoff_s = 0.0
        self.failures = 0

    def resend(self) -> None:
        """Sends the next report right away, even if nothing changed: tracking just came back on."""
        self.sent_front = None
        self.retry_at = 0.0

    def report(self, app_name: str, site: str | None = None) -> None:
        now = self.clock()
        front = describe_front(app_name, site)
        if front != self.seen_front:
            logger.info("front app: %s", front)
            self.seen_front = front
        changed = front != self.sent_front
        heartbeat_due = now - self.sent_at >= HEARTBEAT_INTERVAL_S
        if (changed or heartbeat_due) and now >= self.retry_at:
            self.send(app_name, site, now)

    def send(self, app_name: str, site: str | None, now: float) -> None:
        result = self.deliver(app_name, site)
        if result.delivered:
            if self.failures:
                logger.info("reached the Pi again after %d failed tries", self.failures)
            self.sent_front = describe_front(app_name, site)
            self.sent_at = now
            self.failures = 0
            self.backoff_s = 0.0
            self.retry_at = 0.0
        else:
            self.failures += 1
            self.backoff_s = min(max(self.backoff_s * 2, FIRST_BACKOFF_S), MAX_BACKOFF_S)
            self.retry_at = now + self.backoff_s
            logger.warning(
                "couldn't send %r, trying again in %.0f s: %s",
                describe_front(app_name, site),
                self.backoff_s,
                result.problem,
            )


class TrackingSwitch:
    """The dashboard's on/off switch for this helper, as last heard from the Pi.

    It starts on. refresh() asks the Pi every TRACKING_CHECK_S, and hear() also takes the
    answer off each report's reply. When the Pi can't say, the last answer stands.
    """

    def __init__(self, check: Callable[[], bool | None], clock: Callable[[], float], on_resume: Callable[[], None]) -> None:
        self.check = check
        self.clock = clock
        self.on_resume = on_resume
        self.enabled = True
        self.checked_at: float | None = None

    def refresh(self) -> None:
        now = self.clock()
        if self.checked_at is None or now - self.checked_at >= TRACKING_CHECK_S:
            self.checked_at = now
            self.hear(self.check())

    def hear(self, enabled: bool | None) -> None:
        if enabled is not None and enabled != self.enabled:
            self.enabled = enabled
            if enabled:
                logger.info("tracking is back on from the dashboard, sending the app in front")
                self.on_resume()
            else:
                logger.info("tracking paused from the dashboard: not looking at the front app or any browser")


def watch_front_app(tools: HelperTools, reporter: AppReporter, switch: TrackingSwitch | None = None) -> None:
    """Checks the front app every POLL_INTERVAL_S until Ctrl+C or launchd stops it.

    With a switch that's off, it looks at nothing and only asks the Pi again every TRACKING_CHECK_S.
    """
    detection_failing = False
    site_problems: dict[str, str] = {}  # the last no-site reason logged per browser, so each is said once
    while True:
        started = tools.clock()
        if switch is not None:
            switch.refresh()
        tracking = switch is None or switch.enabled
        if tracking:
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
                site_detection = detect_site(tools.run, detection.app_name)
                if site_detection.problem and site_problems.get(detection.app_name) != site_detection.problem:
                    logger.info("no site from %s: %s", detection.app_name, site_detection.problem)
                    site_problems[detection.app_name] = site_detection.problem
                reporter.report(detection.app_name, site_detection.site)
        interval = POLL_INTERVAL_S if tracking else TRACKING_CHECK_S
        tools.sleep(max(0.0, interval - (tools.clock() - started)))


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

    def pretend_to_send(app_name: str, site: str | None) -> SendResult:
        logger.info("dry run, would POST %s to %s", encode_app(app_name, site).decode("utf-8"), app_url)
        result = SendResult(delivered=True)
        return result

    watch_front_app(tools, AppReporter(pretend_to_send, tools.clock))


def run_for_real(tools: HelperTools) -> None:
    app_url = read_app_url()
    user = read_user()
    client = PiClient(app_url, user, tools.run, tools.send)
    client.load_password()
    logger.info("sending the front app to %s as %s", app_url, user)
    switch = TrackingSwitch(client.read_tracking, tools.clock, on_resume=lambda: reporter.resend())

    def deliver(app_name: str, site: str | None) -> SendResult:
        result = client.send_app(app_name, site)
        switch.hear(result.enabled)
        return result

    reporter = AppReporter(deliver, tools.clock)
    watch_front_app(tools, reporter, switch)


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
