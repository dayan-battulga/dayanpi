# dayanpi

A little web dashboard that runs on my Raspberry Pi 5. It shows how the Pi is doing, streams its camera, and lets me drive my 4WD rover from a browser, on my Mac with the keyboard or on my iPhone with on-screen buttons.

Want the step-by-step commands? That's all in **[MANUAL.md](MANUAL.md)**. This page is the big picture.

---

## What it's for

- **Keeping an eye on the Pi.** CPU, temperature, memory, disk, network speed and uptime, updated live every second, plus 2-minute charts for CPU, temp and memory. There's also a Power card that turns red if the Pi is undervolted or throttling.
- **Seeing what the rover sees.** A live camera feed right on the page.
- **Driving the rover.** Hold `W A S D` on the Mac or the arrow pad on the phone and the wheels move. Let go and they stop.

It's a personal project, so it's built for one person (me) on my own devices, not for a crowd.

---

## How it works

```
 Mac / iPhone browser
        │  HTTPS + login
        ▼
 Tailscale (Serve = private, Funnel = public)
        │
        ▼
 Raspberry Pi 5 ── uvicorn on 127.0.0.1:8000 (systemd service "dayanpi")
        ├─ collector.py   → reads /proc, /sys and vcgencmd for the stats
        ├─ camera.py      → one thread owns /dev/video0, serves MJPEG at /video
        ├─ drivetrain.py  → drives the L298N motor driver through gpiozero
        └─ static/        → the dashboard page (app.js for stats, drive.js for driving)
```

- **The app only listens on localhost.** Your home network can't reach it directly. Tailscale is the only way in, and it handles HTTPS for you.
- **Every page and API call needs a login** (HTTP Basic Auth). The username and password live in `/etc/dayanpi.env` on the Pi, never in the repo.
- **Stats go out as a live stream** (Server-Sent Events), so the page updates without refreshing.
- **Driving is plain HTTP.** While you hold a key, the page sends `POST /api/drive` about 7 times a second with how hard to push each side (`left` and `right`, from -1 to 1).
- **The camera and motors are optional at startup.** No camera? The dashboard still runs, and the camera reconnects when you plug it back in. Motors can't start? The rest still works, and the Drive card says "unavailable".

---

## Setting it up (short version)

On the Pi:

1. Clone this repo to `~/Desktop/site-page/dayanpi`.
2. Make a venv that can see apt's `gpiozero` and `lgpio`, then install the rest:
   ```bash
   python3 -m venv --system-site-packages .venv
   .venv/bin/pip install -r requirements.txt
   ```
3. Make sure your user is in the `video` and `gpio` groups (`groups`).
4. Copy `dayanpi.env.example` to `/etc/dayanpi.env`, pick a username and strong password, and lock the file down (`chmod 600`, owned by root).
5. Install and start the systemd service from `dayanpi.service`.
6. Expose it with Tailscale: `sudo tailscale serve --bg 8000`.

Then open **https://dayoon.tail279594.ts.net/** and log in.

The full commands, with checks after each one, are in [MANUAL.md → First-time setup](MANUAL.md#first-time-setup-pi).

---

## Using it day to day

- **Making changes:** edit on the Mac, push `main`, then on the Pi run `git pull` and `sudo systemctl restart dayanpi`.
- **Looking around:** open the site, log in, and watch the stats, charts and camera.
- **Driving:** use the **Drive** card under the camera.
  - Mac: `W`/`S` for forward/back, `A`/`D` to spin, and combos like `W`+`A` to arc.
  - Phone: the same moves on the ▲ ◀ ▶ ▼ pad; two thumbs work for arcs.
- **When something's off:** check `journalctl -u dayanpi -n 50 --no-pager` on the Pi, then the Troubleshooting table in the manual.

---

## Turning it off and on

Everything comes back by itself after a reboot or power cut, as long as the `dayanpi` service is enabled (`systemctl is-enabled dayanpi`) and Serve was set up with `--bg` (`tailscale serve status`).

- **Off:** motor battery off first, then `sudo poweroff` on the Pi, then unplug once the green light stops blinking. Pulling the plug without shutting down can corrupt the SD card.
- **On:** plug in the Pi, wait about a minute, and open the site. Then put the rover on a box and turn the motor battery on.
- **Only the motor battery unplugged:** if it only powers the motors, the site keeps running and the wheels just won't move until it's back.

Details and a "missing something after boot?" checklist: [MANUAL.md → Unplugging and powering back on](MANUAL.md#unplugging-and-powering-back-on).

---

## Safety (please read before driving)

- **The watchdog.** If the Pi hears nothing for 0.5 s (dead phone, crashed tab, dropped Wi-Fi), it stops the wheels.
- **The speed cap.** The Pi never goes above `MAX_SPEED` (60% power), whatever the browser sends.
- **The reversal pause.** Flipping a side from forward to backward stops it for a moment first, so the motors don't slam into reverse.
- **The battery switch is the real emergency stop.** All of the above is software. If the Pi crashes hard, the motors can keep doing whatever they were doing.
- **Test new code with the wheels up on a box.**
- **Use Serve, not Funnel.** Serve plus the Tailscale app on your phone keeps the site private to your own devices. Funnel puts the login page on the public internet, and now that the site can move a robot, that's not worth it.

Speeds and timings (`SPEED_FLOOR`, `MAX_SPEED`, the watchdog timeout, and so on) are tunable. See [MANUAL.md → Tuning](MANUAL.md#tuning).

---

## Running the tests (on the Mac)

The tests fake the GPIO pins, so no Pi or motors are needed:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
```

They cover the motor logic (speed scaling, clamping, reversal pause, pin order), the watchdog timing, the `/api/drive` route (login, validation, 503 without motors), and startup without a camera or motors.

---

## What's in the repo

| File | What it is |
| --- | --- |
| `app.py` | The FastAPI app: login, routes, rate limits, startup and shutdown, drive watchdog |
| `collector.py` | Reads the Pi's stats |
| `camera.py` | Camera capture thread (one opener, many viewers) |
| `drivetrain.py` | Motor control: speed scaling, reversal pause, and the watchdog's timer |
| `static/` | The dashboard: `index.html`, `styles.css`, `app.js` (stats and camera), `drive.js` (driving) |
| `tests/` | Mac tests (pytest with gpiozero's mock pins) |
| `dayanpi.service` | The systemd unit for the Pi |
| `dayanpi.env.example` | Template for the login file |
| `MANUAL.md` | How to set up, run, drive, tune and fix it |
