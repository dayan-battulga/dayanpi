"""The small once-a-second pictures on the room's seats (study room step 7).

A browser that's tracking sends one with its reading, as base64 in the JSON (every write is JSON); my tile is the front
Pi camera's latest frame, shrunk here. Either way it's a PICTURE_WIDTH x PICTURE_HEIGHT JPEG kept on the desk in memory
(Desk.picture), never written anywhere, and app.py only keeps or serves one through sharing.share_parts.
"""

import base64
import binascii

import cv2
import numpy as np

PICTURE_WIDTH = 320
PICTURE_HEIGHT = 180
PICTURE_QUALITY = 50  # measured on real desk frames: about 6.6 KB each at 320 x 180
# What a browser may send: a little over our own size, so a laptop that rounds differently still gets through.
PICTURE_MAX_WIDTH = 640
PICTURE_MAX_HEIGHT = 360
PICTURE_MAX_BYTES = 32 * 1024
PICTURE_MAX_BASE64 = (PICTURE_MAX_BYTES * 4) // 3 + 4
JPEG_START = b"\xff\xd8"


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
    """The JPEG a browser sent, or None for anything that isn't a real JPEG of about the seat's size. It's served to
    other people as image/jpeg, so it has to decode as one."""
    try:
        jpeg = base64.b64decode(sent, validate=True)
    except (binascii.Error, ValueError):
        jpeg = b""
    picture = None
    if JPEG_START == jpeg[:2] and len(jpeg) <= PICTURE_MAX_BYTES:
        frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is not None and frame.shape[1] <= PICTURE_MAX_WIDTH and frame.shape[0] <= PICTURE_MAX_HEIGHT:
            picture = jpeg
    return picture
