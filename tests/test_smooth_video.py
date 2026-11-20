import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dayanpi.focus.smooth_video import STUN_SERVER, TURN_REFRESH_BEFORE_S, TURN_RETRY_S, TURN_TTL_S, SmoothVideo, TurnClient, read_ice_servers, read_smooth_video

TOKEN = "secret-turn-token-123"
ICE = [{"urls": ["stun:stun.cloudflare.com:3478"]}, {"urls": ["turn:turn.cloudflare.com:3478?transport=udp", "turns:turn.cloudflare.com:443"], "username": "u1", "credential": "c1"}]


def test_off_unless_the_setting_says_on_and_turn_only_with_both_keys():
    assert read_smooth_video({}).describe(0) == {"smooth_video": False, "ice_servers": []}, "nothing outside in the page"
    assert read_smooth_video({"DAYANPI_SMOOTH_VIDEO": "yes", "DAYANPI_TURN_KEY_ID": "k", "DAYANPI_TURN_API_TOKEN": "t"}).enabled is False
    stun_only = read_smooth_video({"DAYANPI_SMOOTH_VIDEO": "on"})
    assert (stun_only.turn, stun_only.describe(0)) == (None, {"smooth_video": True, "ice_servers": [STUN_SERVER]})
    assert read_smooth_video({"DAYANPI_SMOOTH_VIDEO": "on", "DAYANPI_TURN_KEY_ID": "k"}).turn is None, "both TURN settings or none"
    assert read_smooth_video({"DAYANPI_SMOOTH_VIDEO": "on", "DAYANPI_TURN_API_TOKEN": "t"}).turn is None
    assert isinstance(read_smooth_video({"DAYANPI_SMOOTH_VIDEO": "On", "DAYANPI_TURN_KEY_ID": "k", "DAYANPI_TURN_API_TOKEN": "t"}).turn, TurnClient)
    assert read_smooth_video({"DAYANPI_TURN_KEY_ID": "k", "DAYANPI_TURN_API_TOKEN": "t"}).turn is None, "keys alone do nothing"


def test_only_ice_server_urls_and_string_credentials_get_through():
    assert read_ice_servers(ICE) == ICE
    assert read_ice_servers({"urls": "turn:x:3478", "username": "u", "credential": "c"}) == [{"urls": ["turn:x:3478"], "username": "u", "credential": "c"}]
    assert read_ice_servers([{"urls": ["http://evil", "javascript:x"]}, {"urls": 5}, "nope", None, {"urls": ["stun:ok"], "username": 7}]) == [{"urls": ["stun:ok"]}]


class FakeCloudflare:
    """A local stand-in for rtc.live.cloudflare.com: records each request and answers with ICE, or a status."""

    def __init__(self, status: int = 201) -> None:
        self.requests: list[dict] = []
        self.status = status
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "authorization": self.headers["Authorization"], "body": body})
                reply = json.dumps({"iceServers": ICE} if fake.status < 300 else {"errors": ["no"]}).encode()
                self.send_response(fake.status)
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def client(self) -> TurnClient:
        return TurnClient("key/1", TOKEN, host="127.0.0.1", port=self.server.server_address[1], https=False)


@pytest.fixture
def cloudflare():
    fake = FakeCloudflare()
    yield fake
    fake.server.shutdown()


def test_turn_credentials_are_asked_for_once_and_kept_until_just_before_they_expire(cloudflare, caplog):
    client = cloudflare.client()
    assert client.find_servers(1000.0) == ICE
    assert cloudflare.requests == [{"path": "/v1/turn/keys/key%2F1/credentials/generate-ice-servers", "authorization": f"Bearer {TOKEN}", "body": {"ttl": TURN_TTL_S}}]
    assert client.find_servers(1000.0 + TURN_TTL_S - TURN_REFRESH_BEFORE_S - 1) == ICE
    assert len(cloudflare.requests) == 1, "from the cache"
    client.find_servers(1000.0 + TURN_TTL_S - TURN_REFRESH_BEFORE_S)
    assert len(cloudflare.requests) == 2, "asked again before they run out"
    assert all(TOKEN not in record.getMessage() for record in caplog.records)


def test_a_refused_or_unreachable_ask_means_no_turn_for_a_minute_and_no_token_in_the_log(caplog):
    caplog.set_level(logging.INFO)
    refusing = FakeCloudflare(status=401)
    client = refusing.client()
    assert client.find_servers(0.0) == []
    assert client.find_servers(TURN_RETRY_S - 1) == [] and len(refusing.requests) == 1, "not a call per page"
    client.find_servers(TURN_RETRY_S)
    assert len(refusing.requests) == 2
    refusing.server.shutdown()
    gone = TurnClient("k", TOKEN, host="127.0.0.1", port=1, https=False)
    assert gone.find_servers(0.0) == []
    assert any("401" in record.getMessage() for record in caplog.records)
    assert all(TOKEN not in record.getMessage() for record in caplog.records)


def test_smooth_video_hands_out_stun_and_the_cached_turn(cloudflare):
    smooth = SmoothVideo(True, cloudflare.client())
    assert smooth.describe(0.0) == {"smooth_video": True, "ice_servers": [STUN_SERVER, *ICE]}
    assert TOKEN not in json.dumps(smooth.describe(1.0))
    assert len(cloudflare.requests) == 1
