# dayanpi

A little web dashboard that runs on my Raspberry Pi 5. It shows how the Pi is doing, streams its camera, and lets me drive my 4WD rover from a browser, on my Mac with the keyboard or on my iPhone with on-screen buttons.

Want the step-by-step commands? That's all in **[docs/MANUAL.md](docs/MANUAL.md)**. This page is the big picture.

---

## What it's for

- **Keeping an eye on the Pi.** Temperature (as a gauge), CPU (with a live bar per core), memory and disk, updated live every second, plus a status bar with network speed, uptime, power, the voice, the Mac's front app and the sign mode. If the Pi gets undervolted or throttled, the power entry turns red and an Undervoltage pill shows up at the top.
- **Seeing what the rover sees.** A live camera feed right on the page.
- **Driving the rover.** Hold `W A S D` on the Mac or the arrow pad on the phone and the wheels move. Let go and they stop. (Paused right now; the Drive card is hidden.)
- **Tracking focus.** The webcam watches my desk and works out whether I'm focused, on my phone, or away. The Focus card shows a live timer, a timeline of the day from 6 am to midnight, and today's focus and phone time, pickups, time since the last pickup, snacks and best streak. Next to the camera, "What the Pi sees" shows the detector's live numbers. The camera itself stays hidden until you press **Peek**, and then it shows boxes around whatever the detector counted (you, a phone, food, a drink). Every change gets logged on the Pi. It all runs on the Pi, with no video saved.
- **Light and dark.** The page follows your device's light or dark setting. The sun/moon button flips it, and your browser remembers the choice.

It's a personal project, so it's built for one person (me) on my own devices, not for a crowd.

---

## How it works

```
 Mac / iPhone browser
        │  HTTPS + login
        ▼
 Tailscale Serve (private to my devices)
        │
        ▼
 Raspberry Pi 5 ── uvicorn on 127.0.0.1:8000 (systemd service "dayanpi")
        └─ dayanpi/ (the Python package)
             ├─ app.py      → login, routes, startup and shutdown
             ├─ hardware/   → collector (stats), camera (one thread owns the webcam), voice, drivetrain
             ├─ vision/     → detector (people, phones, faces, food), pose, gestures
             ├─ focus/      → the focus state machine, its worker thread, the log tools
             ├─ sign/       → the LED sign renderer, font and icons, page controller
             └─ static/     → the dashboard page (app.js for stats, theme and camera, focus.js for the Focus card)
```

- **The app only listens on localhost.** Your home network can't reach it directly. Tailscale is the only way in, and it handles HTTPS for you.
- **Every page and API call needs a login** (HTTP Basic Auth). The username and password live in `/etc/dayanpi.env` on the Pi, never in the repo.
- **Stats go out as a live stream** (Server-Sent Events), so the page updates without refreshing.
- **Driving is plain HTTP.** While you hold a key, the page sends `POST /api/drive` about 7 times a second with how hard to push each side (`left` and `right`, from -1 to 1).
- **The camera and motors are optional at startup.** No camera? The dashboard still runs, and the camera reconnects when you plug it back in. Motors can't start? The rest still works, and the Drive card says "unavailable".

---

## Setup, power and safety

The step-by-step versions live in the manual, with a check after each step:

- [First-time setup](docs/MANUAL.md#first-time-setup-pi): the venv, groups, password file and systemd service. Then [Tailscale Serve](docs/MANUAL.md#tailscale-serve) puts it on your devices.
- [Unplugging and powering back on](docs/MANUAL.md#unplugging-and-powering-back-on): what has to stay enabled, and the safe shutdown order.
- [Driving the rover](docs/MANUAL.md#driving-the-rover): the watchdog, speed cap, reversal pause and tuning. Read it before driving.

---

## Using it day to day

- **Making changes:** edit on the Mac, push `main`, then on the Pi run `git pull` and `sudo systemctl restart dayanpi`.
- **Looking around:** open the site, log in, and watch the Focus card and the stats. Press **Peek** to see the camera.
- **Driving:** use the **Drive** card under the camera.
  - Mac: `W`/`S` for forward/back, `A`/`D` to spin, and combos like `W`+`A` to arc.
  - Phone: the same moves on the ▲ ◀ ▶ ▼ pad; two thumbs work for arcs.
- **When something's off:** check `journalctl -u dayanpi -n 50 --no-pager` on the Pi, then the Troubleshooting table in the manual.

---

## Running the tests (on the Mac)

The tests fake the GPIO pins, so no Pi or motors are needed:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
```

They cover the focus state machine (driven with fake clocks), the detector decoding, the sign renderer, the worker thread, the motor logic and watchdog, the API routes (login, validation, 503 without motors), and startup without a camera or motors. `pyproject.toml` tells pytest where the tests and the package are, so plain `pytest` from the repo root works too.

---

## What's in the repo

The Python code is one package, `dayanpi/`, split by what it talks to. Everything that isn't code sits next to it at the top level.

| Path | What it is |
| --- | --- |
| `dayanpi/app.py` | The FastAPI app: login, routes, startup and shutdown, drive watchdog |
| `dayanpi/paths.py` | Where `static/`, `models/`, `data/` and `focus_check/` live, so no module counts parent folders |
| `dayanpi/hardware/` | Things attached to the Pi: `collector.py` (stats), `camera.py` (one thread owns the webcam, many viewers), `voice.py` (the USB speaker), `drivetrain.py` (the L298N motors, paused) |
| `dayanpi/vision/` | The models: `detector.py` (people, phones, faces, food and drinks), `pose.py` (body points), `gestures.py` (arm gestures that flip the sign and toggle work blocks) |
| `dayanpi/focus/` | `tracker.py` (readings → focused / phone / away, today's totals, the log), `worker.py` (the thread that scans a frame about once a second), `stats.py` (the day report), `check.py` (the guided detector check) |
| `dayanpi/sign/` | The LED sign: `renderer.py` (pages drawn with numpy), `glyphs.py` (the 5x7 font and 16x16 icons), `controller.py` (what shows when) |
| `dayanpi/utils/` | `threads.py`: the start/tick/stop base the worker and the sign share |
| `dayanpi/static/` | The dashboard: `index.html`, `styles.css` (both palettes and all the motion), `ui.js` (helpers the scripts share), `app.js` (stats, theme toggle, camera), `focus.js` (Focus card, detector readings, sign, Today list), `drive.js` (driving, not loaded while the rover is paused) |
| `scripts/` | What you run by hand on the Pi: `focus_check.py` and `focus_stats.py` |
| `models/` | The ONNX models: YOLO11 nano (objects), YuNet (faces), and YOLO11 nano pose once it's exported |
| `mac_helper/` | The Mac-side helper that reports the front app to the Pi (see its README) |
| `tests/` | Mac tests (pytest, with gpiozero's mock pins for the motors) |
| `deploy/` | `dayanpi.service` (the systemd unit) and `dayanpi.env.example` (template for the login file) |
| `docs/MANUAL.md` | How to set up, run, drive, tune and fix it |
| `data/`, `focus_check/` | Written on the Pi at runtime (the focus log, the check's snapshots); both gitignored |
