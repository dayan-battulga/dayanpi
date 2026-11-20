"""Smooth video on the room's seats: browsers send each other their camera with WebRTC, and the Pi only introduces them.

Off unless DAYANPI_SMOOTH_VIDEO=on. Then the page gets Cloudflare's free STUN server, which the browsers ask for their
own public address (the Pi never talks to it), and the signaling rides on the talk socket (app.py, focus/talk.py).
With DAYANPI_TURN_KEY_ID and DAYANPI_TURN_API_TOKEN set too, the Pi asks Cloudflare for short-lived TURN credentials,
the relay for networks that block direct connections, and keeps them until shortly before they expire. That request is
the Pi's only outside call, the token never leaves the Pi or reaches a log, and the credentials only go to signed-in
room members (GET /api/rtc). WebRTC is encrypted end to end, so a relay passes video along without being able to see it.
"""

import http.client
import json
import logging
import os
import threading
from urllib.parse import quote

SMOOTH_VIDEO_ENV = "DAYANPI_SMOOTH_VIDEO"
TURN_KEY_ENV = "DAYANPI_TURN_KEY_ID"
TURN_TOKEN_ENV = "DAYANPI_TURN_API_TOKEN"
STUN_SERVER = {"urls": "stun:stun.cloudflare.com:3478"}  # needs no account; the browsers talk to it, not the Pi
TURN_HOST = "rtc.live.cloudflare.com"
TURN_TTL_S = 4 * 3600  # how long Cloudflare's credentials last
TURN_REFRESH_BEFORE_S = 15 * 60  # asked for again this long before they run out, so nobody gets a nearly dead pair
TURN_RETRY_S = 60.0  # after a failed ask, the next one waits this long, so a bad token doesn't mean a call per page
TIMEOUT_S = 10.0
ICE_URL_SCHEMES = ("stun:", "turn:", "turns:")
ICE_FIELD_MAX = 512

logger = logging.getLogger(__name__)


def read_ice_servers(reply: object) -> list[dict]:
    """Cloudflare's iceServers (a list, or one object), keeping only stun:/turn:/turns: URLs and string credentials."""
    entries = reply if isinstance(reply, list) else [reply]
    servers = []
    for entry in entries:
        urls = entry.get("urls") if isinstance(entry, dict) else None
        urls = [urls] if isinstance(urls, str) else urls
        kept = [url for url in urls if isinstance(url, str) and url.startswith(ICE_URL_SCHEMES) and len(url) <= ICE_FIELD_MAX] if isinstance(urls, list) else []
        credentials = {key: entry[key] for key in ("username", "credential") if isinstance(entry.get(key), str) and len(entry[key]) <= ICE_FIELD_MAX} if kept else {}
        if kept:
            servers.append({"urls": kept} | credentials)
    return servers


class TurnClient:
    """Cloudflare's TURN credentials for the room, asked for when needed and kept until TURN_REFRESH_BEFORE_S before they
    expire. Thread-safe: GET /api/rtc runs in the thread pool. The host is fixed; port and https are for the tests'
    fake server."""

    def __init__(self, key_id: str, token: str, host: str = TURN_HOST, port: int = 443, https: bool = True) -> None:
        self._key_id = key_id
        self._token = token
        self._host = host
        self._port = port
        self._https = https
        self._lock = threading.Lock()
        self._servers: list[dict] = []
        self._good_until = 0.0  # ask again from here on
        self.asked = 0  # how many times it called Cloudflare, for the tests

    def find_servers(self, now: float) -> list[dict]:
        """The TURN servers with their credentials, from the cache while they're good, else asked for once."""
        with self._lock:
            if now >= self._good_until:
                self._servers = self._ask()
                self._good_until = now + (TURN_TTL_S - TURN_REFRESH_BEFORE_S if self._servers else TURN_RETRY_S)
            servers = self._servers
        return servers

    def _ask(self) -> list[dict]:
        self.asked += 1
        path = f"/v1/turn/keys/{quote(self._key_id, safe='')}/credentials/generate-ice-servers"
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        connection_class = http.client.HTTPSConnection if self._https else http.client.HTTPConnection
        connection = connection_class(self._host, self._port, timeout=TIMEOUT_S)
        servers: list[dict] = []
        try:
            connection.request("POST", path, body=json.dumps({"ttl": TURN_TTL_S}), headers=headers)
            response = connection.getresponse()
            data = json.loads(response.read() or b"{}")
            servers = read_ice_servers(data.get("iceServers")) if response.status in (200, 201) and isinstance(data, dict) else []
            if not servers:
                logger.warning("Cloudflare gave no TURN credentials (HTTP %s); smooth video uses direct connections only", response.status)
        except (OSError, http.client.HTTPException, ValueError) as error:
            logger.warning("couldn't reach Cloudflare for TURN credentials (%s); smooth video uses direct connections only", type(error).__name__)
        finally:
            connection.close()
        return servers


class SmoothVideo:
    """Whether smooth video is on, and the ICE servers a member's browser gets for it."""

    def __init__(self, enabled: bool, turn: TurnClient | None) -> None:
        self.enabled = enabled
        self.turn = turn

    def describe(self, now: float) -> dict:
        """GET /api/rtc's answer: nothing at all while it's off, so the page has no outside server in it."""
        servers = ([STUN_SERVER] + (self.turn.find_servers(now) if self.turn is not None else [])) if self.enabled else []
        described = {"smooth_video": self.enabled, "ice_servers": servers}
        return described


def read_smooth_video(environ: dict | None = None) -> SmoothVideo:
    """From the environment: on only with DAYANPI_SMOOTH_VIDEO=on, TURN only with both of its settings as well."""
    env = os.environ if environ is None else environ
    enabled = env.get(SMOOTH_VIDEO_ENV, "").strip().lower() == "on"
    key_id, token = env.get(TURN_KEY_ENV, "").strip(), env.get(TURN_TOKEN_ENV, "").strip()
    smooth = SmoothVideo(enabled, TurnClient(key_id, token) if enabled and key_id and token else None)
    return smooth
