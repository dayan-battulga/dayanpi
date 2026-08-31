"""Throwaway: prove OpenCV MJPEG passthrough (no decode/re-encode).

Run on the Pi, then delete this file once it passes.
"""

import cv2

DEVICE_PATH = "/dev/video0"
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

cap = cv2.VideoCapture(DEVICE_PATH, cv2.CAP_V4L2)
if not cap.isOpened():
    raise SystemExit(f"failed to open {DEVICE_PATH}")

# Order matters: format before resolution.
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

ok, frame = cap.read()
cap.release()

if not ok or frame is None:
    raise SystemExit("cap.read() failed")

print("shape:", frame.shape)
print("first two bytes:", frame.flatten()[:2].tolist())

# Passthrough: flat JPEG buffer starting with 0xFF 0xD8.
# Failure: shape like (480, 640, 3) — decoded BGR.
flat = frame.flatten()
if flat.size >= 2 and int(flat[0]) == 255 and int(flat[1]) == 216:
    open("test.jpg", "wb").write(frame.tobytes())
    print("passthrough OK — wrote test.jpg")
else:
    print("passthrough FAILED — got decoded frames, not raw JPEG")
