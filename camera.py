import threading
import time

import cv2

# Tunables — change these in one place only.
DEVICE_PATH = "/dev/video0"
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FRAME_SKIP = 2  # keep 1 of every N frames when streaming
