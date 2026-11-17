# dayanpi

A little web dashboard that runs on my Raspberry Pi 5. It shows how the Pi is doing, streams its cameras, and tracks whether I'm focused, on my phone or away.

Want the step-by-step commands? Setup and running are in **[docs/MANUAL.md](docs/MANUAL.md)**, and each add-on (focus tracker, Pi camera, voice) has its own guide next to it in [docs/](docs/). This page is the big picture.

---

## What it's for

- **Keeping an eye on the Pi.** Temperature, CPU, memory and uptime on the Pi page, each rolling to its new number every second. If the power supply sags, an Undervoltage warning shows up there in amber.
- **Seeing the desk.** Live camera feeds right on the page.
- **Tracking focus.** The webcam watches my desk and works out whether I'm focused, on my phone, or away. The top of the desk page says it in big letters, with a live timer, a timeline of the day from 6 am to midnight, and today's focus time, phone time and pickups. Next to the camera, "What the Pi sees" shows the detector's live numbers. The camera itself stays hidden until you press **Peek**, and then it shows boxes around whatever the detector counted (you or a phone). Every change gets logged on the Pi. It all runs on the Pi, with no video saved.
- **Light and dark.** The page follows your device's light or dark setting. The sun/moon button flips it, and your browser remembers the choice.

It's a personal project: it's built for me, plus up to three friends with their own invite-only login. For now everything on it is still my data (they can look, not change), and the camera only ever shows to me, on my own devices.

---

## How it works

```
 Mac / iPhone browser
        │  HTTPS, then the /login page
        ▼
 Tailscale Serve (my own devices) or Funnel (the public internet, only with the camera lock on)
        │
        ▼
 Raspberry Pi 5 ── uvicorn on 127.0.0.1:8000 (systemd service "dayanpi")
        └─ dayanpi/ (the Python package)
             ├─ app.py      → the sign-in check, the camera lock, routes, startup and shutdown
             ├─ auth/       → accounts, sign-ins, invites and Mac tokens (SQLite), the account routes
             ├─ hardware/   → collector (stats), camera (one thread owns the webcam), voice
             ├─ vision/     → detector (people, phones, faces), hands, hand signs
             ├─ focus/      → the focus state machine, its worker thread, the log tools
             └─ static/     → the dashboard, built from web/ (React); never edited by hand
```

- **The app only listens on localhost.** Your home network can't reach it directly. Tailscale is the only way in, and it handles HTTPS for you.
- **Every page and API call needs you signed in**, on a real `/login` page with your own account: up to 4, invite only (the owner makes invites in Settings). The sign-in is a cookie, and passwords, sign-ins and tokens are only ever stored hashed, in `data/accounts.db` on the Pi. The first owner account comes from `DAYANPI_USER` / `DAYANPI_PASSWORD` in `/etc/dayanpi.env`, never the repo. See [Accounts](docs/MANUAL.md#accounts).
- **The full camera only answers me, on my own Tailscale devices** (`DAYANPI_TAILSCALE_LOGIN`, see the [camera lock](docs/MANUAL.md#camera-lock)), so the rest of the site can go on Funnel without it.
- **Stats go out as a live stream** (Server-Sent Events), so the page updates without refreshing.
- **The camera is optional at startup.** No camera? The dashboard still runs, and the camera reconnects when you plug it back in.

---

## Setup, power and safety

The step-by-step versions live in the manual, with a check after each step:

- [First-time setup](docs/MANUAL.md#first-time-setup-pi): the venv, groups, password file and systemd service. Then [Tailscale Serve](docs/MANUAL.md#tailscale-serve) puts it on your devices.
- [Unplugging and powering back on](docs/MANUAL.md#unplugging-and-powering-back-on): what has to stay enabled, and the safe shutdown order.

---

## Using it day to day

- **Making changes:** edit on the Mac, push `main`, then on the Pi run `git pull` and `sudo systemctl restart dayanpi`.
- **Looking around:** open the site, sign in, and watch the state and the totals at the top. Press **Peek** to see the camera.
- **When something's off:** check `journalctl -u dayanpi -n 50 --no-pager` on the Pi, then the Troubleshooting table in the manual.

---

## Running the tests (on the Mac)

The tests fake the hardware, so no Pi is needed:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
```

They cover the focus state machine (driven with fake clocks), the detector decoding, the worker thread, the accounts (hashing, invites, sign-ins, the wrong-password wait), the API routes (who can reach what, the camera lock, validation), and startup without a camera. `pyproject.toml` tells pytest where the tests and the package are, so plain `pytest` from the repo root works too.

The dashboard has its own tests (Vitest), for the time and box math, the timeline, the to-do list and the whole page on a fake stream:

```bash
cd web && npm ci && npm test
```

---

## What's in the repo

The Python code is one package, `dayanpi/`, split by what it talks to. Everything that isn't code sits next to it at the top level.

| Path | What it is |
| --- | --- |
| `dayanpi/app.py` | The FastAPI app: the sign-in check, the camera lock, routes, startup and shutdown |
| `dayanpi/auth/` | `accounts.py` (the SQLite store for accounts, sign-ins, invites and Mac tokens, password hashing, the wrong-password wait) and `routes.py` (sign in and out, join, Settings, tokens, invites, accounts) |
| `dayanpi/paths.py` | Where `static/`, `models/`, `data/` and `focus_check/` live, so no module counts parent folders |
| `dayanpi/hardware/` | Things attached to the Pi: `collector.py` (stats), `camera.py` (one thread owns the webcam, many viewers), `voice.py` (the USB speaker), `llm.py` (a small model in Ollama on the Pi, only ever at 127.0.0.1) |
| `dayanpi/vision/` | The models: `detector.py` (people, phones and faces), `hands.py` (hand joints), `gestures.py` (hand signs, like the peace sign that reads your to-dos) |
| `dayanpi/focus/` | `tracker.py` (readings → focused / phone / away, today's totals, the log), `worker.py` (the thread that scans a frame about once a second), `stats.py` (the day report), `check.py` (the guided detector check), `todos.py` (the to-do list and its time), `days.py` (one markdown page per finished day, for the calendar), `coach.py` (what the peace sign says) |
| `dayanpi/utils/` | `threads.py`: the start/tick/stop base the worker and the peace sign's coach share |
| `dayanpi/static/` | The built dashboard (`npm run build` in `web/` writes it); committed so the Pi needs no Node |
| `web/` | The dashboard's source: React + TypeScript + Vite + Tailwind + shadcn/ui, one folder per card in `src/components/`. See "Working on the dashboard" in the manual |
| `models/` | The ONNX models: YOLO26 nano (objects), YuNet (faces), and MediaPipe palm and hand pose (hand signs) |
| `mac_helper/` | The Mac-side helper that reports the front app to the Pi (see its README) |
| `tests/` | Mac tests (pytest) |
| `deploy/` | `dayanpi.service` (the systemd unit) and `dayanpi.env.example` (template for the env file: the first owner login, the camera lock) |
| `docs/` | `MANUAL.md` (set up, run, fix) plus a guide per add-on: `focus-tracker.md`, `pi-camera.md`, `voice.md` |
| `data/`, `focus_check/` | Written on the Pi at runtime (the focus log, `accounts.db`, the check's snapshots); both gitignored |
