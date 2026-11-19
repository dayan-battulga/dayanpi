"""The small once-a-second pictures on the room's seats (study room step 7).

A browser that's tracking sends one with its reading, as base64 in the JSON (every write is JSON); my tile is the front
Pi camera's latest frame, shrunk here. Either way it's a PICTURE_WIDTH x PICTURE_HEIGHT JPEG kept on the desk in memory
(Desk.picture), never written anywhere, and app.py only keeps or serves one through sharing.share_parts.
"""

import base64
import binascii

import cv2
import numpy as np

PICTURE_WIDTH = 640
PICTURE_HEIGHT = 360
# The smallest of 60, 70 and 80 that still looks sharp on a seat on a 2x screen: about 20 KB on real desk frames.
PICTURE_QUALITY = 60
# What a browser may send. The tracker draws exactly our size, so nothing bigger; the bytes are about twice the real
# frames, and their base64 plus the reading's numbers still fits app.MAX_BODY_BYTES.
PICTURE_MAX_WIDTH = PICTURE_WIDTH
PICTURE_MAX_HEIGHT = PICTURE_HEIGHT
PICTURE_MAX_BYTES = 44 * 1024
PICTURE_MAX_BASE64 = (PICTURE_MAX_BYTES * 4) // 3 + 4
JPEG_START = b"\xff\xd8"
# The start-of-frame markers, which carry the picture's size (C4, C8 and CC are other segments).
SIZE_MARKERS = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
# Every other marker libjpeg reads a length after before the first scan: DHT, DAC, DQT, DNL, DRI, APP0-15 and COM.
# TEM, RST0-7 and FF 00 have no length there, and libjpeg skips stray bytes between markers, so a walker that took
# them any other way would land on a different SOF than the one cv2 allocates for.
LENGTH_MARKERS = SIZE_MARKERS | {0xC4, 0xCC, 0xDB, 0xDC, 0xDD, 0xFE} | set(range(0xE0, 0xF0))
SCAN_START = 0xDA


def read_jpeg_size(jpeg: bytes) -> dict | None:
    """{"width", "height"} from a JPEG's header without decoding it, or None when the header never says. It walks the
    markers to the first scan the way libjpeg does and gives up on anything libjpeg could read another way (stray
    bytes, a marker with no length, a length under 2, more than one SOF), so the size is the one cv2 would allocate."""
    at = len(JPEG_START)
    sizes = []
    scanning = False
    while not scanning and at + 4 <= len(jpeg) and jpeg[at] == 0xFF:
        marker = jpeg[at + 1]
        length = int.from_bytes(jpeg[at + 2 : at + 4], "big")
        if marker == 0xFF:
            at += 1  # a fill byte before the next marker
        elif marker == SCAN_START:
            scanning = True
        elif marker in LENGTH_MARKERS and length >= 2:
            if marker in SIZE_MARKERS:
                sizes.append({"height": int.from_bytes(jpeg[at + 5 : at + 7], "big"), "width": int.from_bytes(jpeg[at + 7 : at + 9], "big")})
            at += 2 + length
        else:
            at = len(jpeg)
    return sizes[0] if scanning and len(sizes) == 1 else None


def shrink_frame(jpeg: bytes) -> bytes | None:
    """A camera frame cut to 16:9 from its middle and shrunk to the seat's size, or None when it won't decode."""
    frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    shrunk = None
    if frame is not None:
        height, width = frame.shape[:2]
        crop_height = min(height, round(width * PICTURE_HEIGHT / PICTURE_WIDTH))
        crop_width = min(width, round(height * PICTURE_WIDTH / PICTURE_HEIGHT))
        top, left = (height - crop_height) // 2, (width - crop_width) // 2
        small = cv2.resize(frame[top : top + crop_height, left : left + crop_width], (PICTURE_WIDTH, PICTURE_HEIGHT), interpolation=cv2.INTER_AREA)
        encoded, buffer = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, PICTURE_QUALITY])
        shrunk = buffer.tobytes() if encoded else None
    return shrunk


def read_browser_picture(sent: str) -> bytes | None:
    """The JPEG a browser sent, or None for anything that isn't a real JPEG at most the seat's size. It's served to
    other people as image/jpeg, so it has to decode as one."""
    try:
        jpeg = base64.b64decode(sent, validate=True)
    except (binascii.Error, ValueError):
        jpeg = b""
    picture = None
    # cv2 makes room for whatever size the header claims before it reads a pixel, and a 1 KB file can claim 30000 x 30000
    # (2.7 GB), so the size is checked first.
    size = read_jpeg_size(jpeg) if JPEG_START == jpeg[:2] and len(jpeg) <= PICTURE_MAX_BYTES else None
    if size is not None and size["width"] <= PICTURE_MAX_WIDTH and size["height"] <= PICTURE_MAX_HEIGHT:
        frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is not None and frame.shape[1] <= PICTURE_MAX_WIDTH and frame.shape[0] <= PICTURE_MAX_HEIGHT:
            picture = jpeg
    return picture
