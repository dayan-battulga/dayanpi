# dayanpi: notes for Claude Code

## What this repo is
A FastAPI dashboard for my Raspberry Pi 5 (stats, charts, camera). I'm adding a controller so I can drive my 4WD rover from this site. MANUAL.md explains how the app runs. If anything in this file disagrees with the code or MANUAL.md, trust those and tell me.

## How it runs
- I edit on my Mac (this repo), push main, pull on the Pi at ~/Desktop/site-page/dayanpi, and run `sudo systemctl restart dayanpi`.
- uvicorn serves on 127.0.0.1:8000 under systemd (dayanpi.service, runs as user dayoon). Tailscale Serve/Funnel exposes it at https://dayoon.tail279594.ts.net.
- Every HTTP route sits behind the Basic Auth middleware in app.py. That middleware does not run for WebSocket connections, so don't add WebSocket routes.
- Rate limits (slowapi): /api/stats and /api/health are 60/minute, /api/drive is 600/minute (one held key sends about 420), /api/stream is 5/minute, /video is 30/minute, and the static dashboard files have none. Limits are keyed on the client IP, and behind Tailscale every request comes from 127.0.0.1, so each limit is shared by everyone.
- Startup fails if DAYANPI_USER or DAYANPI_PASSWORD is missing, or if /sys/class/net/wlan0 doesn't exist (sampler.sample() runs at startup). A missing camera doesn't stop startup: stream.start() logs a warning and the capture loop keeps retrying. Neither do motor problems (GPIO busy, dayoon not in the gpio group, gpiozero/lgpio not visible to the venv): DriveTrain() failing is logged, the dashboard runs without motors, and /api/drive returns 503.
- You run on my Mac. You can't reach the Pi, its GPIO, or its camera. When something needs the Pi, give me the exact commands and I'll run them.

## Rover hardware
- L298N motor driver, two motors per side wired together.
- Left: IN1 = GPIO17, IN2 = GPIO27, ENA = GPIO12. Right: IN3 = GPIO22, IN4 = GPIO23, ENB = GPIO13. IN1 or IN3 high means forward.
- Use gpiozero: DigitalOutputDevice for the IN pins, PWMOutputDevice for the EN pins. Don't use gpiozero's Motor class; it puts PWM on the IN pins and holds EN high.
- To change a side's speed or direction: set EN to 0, then set the IN pins, then set EN to the new speed.
- On the Pi, gpiozero and lgpio come from apt. The venv sees them through system site packages: MANUAL.md creates it with `python3 -m venv --system-site-packages .venv`, and an older venv gets `include-system-site-packages = true` in .venv/pyvenv.cfg. Don't add gpiozero or lgpio to requirements.txt. For Mac tests, requirements-dev.txt pulls in requirements.txt plus gpiozero, pytest and httpx; use gpiozero's MockFactory with MockPWMPin.
- The motor code is drivetrain.py (DriveTrain, MotorSide). app.py creates the DriveTrain at startup, so while the dayanpi service runs it owns the motor pins, and other scripts get "GPIO busy".

## Ground rules
- Never commit or push. Leave changes uncommitted and finish with a list of changed files.
- One step at a time. Stop when a step is done and wait for me.
- No calls to outside services or endpoints unless I explicitly say so for that run.
- Code style for new code: noun-first class names, verb-first function names, one return per function, no tuple returns, repeated code goes in a utils module, descriptive names for returned values, comments only for real traps. The existing code (app.py, camera.py, collector.py) doesn't all follow these; don't refactor it to match unless I ask.
- Finish every step with the Mac tests you ran and their results, plus the exact commands for me to test it on the Pi.
- Write docs (like MANUAL.md) in plain, casual language.
