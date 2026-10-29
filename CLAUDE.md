# dayanpi: notes for Claude Code

## What this repo is
A FastAPI dashboard for my Raspberry Pi 5 (stats, charts, camera). It can also drive my 4WD rover, but the rover is paused: the motors are unplugged from the Pi and the Drive card is hidden. Right now I'm building a focus tracker: the webcam sits at my desk and the site shows whether I'm working, on my phone, or away. MANUAL.md explains how the app runs. If anything in this file disagrees with the code or MANUAL.md, trust those and tell me.

## How it runs
- Code gets pushed to main, either by you from a cloud session or by me from my Mac. I pull on the Pi at ~/Desktop/site-page/dayanpi and run `sudo systemctl restart dayanpi`.
- uvicorn serves on 127.0.0.1:8000 under systemd (dayanpi.service, runs as user dayoon). Tailscale Serve/Funnel exposes it at https://dayoon.tail279594.ts.net.
- Every HTTP route sits behind the Basic Auth middleware in app.py. That middleware does not run for WebSocket connections, so don't add WebSocket routes.
- Rate limits (slowapi): /api/stats, /api/health and /api/focus are 60/minute, /api/focus/block is 30/minute, /api/mac/app is 120/minute, /api/drive is 600/minute (one held key sends about 420), /api/stream is 5/minute, /video is 30/minute, and the static dashboard files have none. Limits are keyed on the client IP, and behind Tailscale every request comes from 127.0.0.1, so each limit is shared by everyone.
- Startup fails if DAYANPI_USER or DAYANPI_PASSWORD is missing, or if /sys/class/net/wlan0 doesn't exist (sampler.sample() runs at startup). A missing camera doesn't stop startup: stream.start() logs a warning and the capture loop keeps retrying. Neither do motor problems (GPIO busy, dayoon not in the gpio group, gpiozero/lgpio not visible to the venv): DriveTrain() failing is logged, the dashboard runs without motors, and /api/drive returns 503.
- You run in a cloud session or on my Mac, never on the Pi. You can't reach the Pi, its GPIO, or its camera. When something needs the Pi, give me the exact commands and I'll run them.

## Focus tracker
- The webcam is at my desk now, pointed at my face, hands and desk. Plan, one step at a time: (1) detector check, (2) turn detections into steady states (working / phone / away), (3) run it inside the app and log state changes on the Pi, (4) dashboard card with the current state, today's totals and a timeline, (5) extras. Steps 1-4 are done.
- The pieces: detector.py (models), focus.py (FocusTracker state machine, DayTotals, Callouts, FocusLog, replay_day/total_day), focus_worker.py (the thread that scans a frame about once a second and feeds the tracker), focus_stats.py (CLI over the log), static/focus.js (the card). app.py starts the worker in lifespan, restores today from the log first, puts tracker.status() into every SSE snapshot as "focus", and serves /api/focus, /api/focus/block and /api/mac/app.
- The rules live as constants at the top of focus.py: person >= 0.5 for 2 checks = present; phone >= 0.25 in 3 of the last 5 checks = on phone, out after 5 misses; 10 s without a person = away; 30 s without frames = unknown; food >= 0.3 in 3 of 5 = a snack, one per sitting. Every time-based rule takes `now` from the caller; tests drive it with fake clocks.
- The log is data/focus_log/YYYY-MM-DD.jsonl (DAYANPI_DATA_DIR overrides data/). Lines: state, pickup, snack, callout, block, mac_app, sample (every 30 s), day_summary, day_start, restart. Never frames. FocusTracker.restore() rebuilds today from it after a restart (loses at most 30 s).
- Callouts (focus.Callout, speak=False means sign/log only): instant_pickup, late_night_phone, long_break, break_over (during a block), day_done, snack. app.handle_focus_update fans them out: speak=True goes to voice.say().
- voice.py: VoiceAnnouncer speaks through ALSA aplay (a systemd system service can't reach the desktop's PipeWire). DAYANPI_VOICE = off (default, logs "would say") | espeak | piper; DAYANPI_PIPER_MODEL, DAYANPI_AUDIO_DEVICE. A voice that can't run logs one error and stays off. POST /api/voice/say (30/minute) is for trying the speaker.
- pose.py + gestures.py: with models/yolo11n-pose_480x640.onnx present, focus_worker uses PoseDeskScanner (pose model for the full-frame pass) and runs GestureTracker each check. Gestures: right hand up 1 s = next_page, left = previous_page, both 2 s = toggle_block. app.handle_gesture logs the gesture, toggles the block and speaks; page flips go to the sign controller.
- app.py calls logging.basicConfig(INFO) at import, because uvicorn only configures its own loggers and the app's INFO lines would otherwise never reach journalctl.
- detector.py runs two ONNX models through plain OpenCV (cv2.dnn and cv2.FaceDetectorYN), so the Pi needs no new pip packages. The models live in models/: YOLO11 nano (COCO, exported at 640x480; class 0 = person, 67 = cell phone) and YuNet for faces.
- Phones come from a second YOLO pass on a crop around the main person (person >= 0.5, box plus margin); full-frame phone hits are ignored. On my real desk frames that took a phone in hand from 10% to 80% of checks at >= 0.3, with no hits while working. It roughly doubles the time per check.
- camera.py is the only thing that may open the camera. Inside the app, read frames from app.stream (camera.create_stream() picks the backend: DAYANPI_CAMERA = auto (default) | usb | picamera; PiCameraStream wraps picamera2 behind the same latest_frame/frame_after interface and skips USB webcams that libcamera also lists; DAYANPI_USB_DEVICE names the webcam, ideally a /dev/v4l/by-id path since /dev/video0 can move once a CSI camera is plugged in). Standalone scripts like focus_check.py need `sudo systemctl stop dayanpi` first.
- Never save video or frames on the Pi, except focus_check.py's snapshots in focus_check/ (gitignored). Only state changes get logged.
- The site shows a camera pointed at me all day, so it stays on Tailscale Serve, not Funnel.

## Rover hardware (paused)
- To bring driving back: plug the motors back in (pin table below), remove `hidden` from #drive-card in static/index.html, and add `<script type="module" src="/drive.js"></script>` back after app.js.
- L298N motor driver, two motors per side wired together.
- Left: IN1 = GPIO17, IN2 = GPIO27, ENA = GPIO12. Right: IN3 = GPIO22, IN4 = GPIO23, ENB = GPIO13. IN1 or IN3 high means forward.
- Use gpiozero: DigitalOutputDevice for the IN pins, PWMOutputDevice for the EN pins. Don't use gpiozero's Motor class; it puts PWM on the IN pins and holds EN high.
- To change a side's speed or direction: set EN to 0, then set the IN pins, then set EN to the new speed.
- On the Pi, gpiozero and lgpio come from apt. The venv sees them through system site packages: MANUAL.md creates it with `python3 -m venv --system-site-packages .venv`, and an older venv gets `include-system-site-packages = true` in .venv/pyvenv.cfg. Don't add gpiozero or lgpio to requirements.txt. For Mac tests, requirements-dev.txt pulls in requirements.txt plus gpiozero, pytest and httpx; use gpiozero's MockFactory with MockPWMPin.
- The motor code is drivetrain.py (DriveTrain, MotorSide). app.py creates the DriveTrain at startup, so while the dayanpi service runs it owns the motor pins, and other scripts get "GPIO busy".

## Ground rules
- You can commit and push to main. One commit per step, with a message that says what changed, and only after the tests for what changed pass. Finish with the list of changed files.
- One step at a time. Stop when a step is done and wait for me.
- No calls to outside services or endpoints unless I explicitly say so for that run.
- Code style for new code: noun-first class names, verb-first function names, one return per function, no tuple returns, repeated code goes in a utils module, descriptive names for returned values, comments only for real traps. The existing code (app.py, camera.py, collector.py) doesn't all follow these; don't refactor it to match unless I ask.
- Finish every step with the tests you ran (only the ones covering what changed) and their results, plus the exact commands for me to test it on the Pi.
- Write docs (like MANUAL.md) in plain, casual language.
