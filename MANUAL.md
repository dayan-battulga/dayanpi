# dayanpi — Run Manual

Live telemetry dashboard for a Raspberry Pi 5: stats, charts, SSE updates, and a camera feed.

After Stage 7 the app is password-protected and bound to **localhost only**. You reach it through Tailscale Serve (private) or Funnel (public).

---

## Overview

| Machine | Role |
| --- | --- |
| **Mac** | Edit code, push to GitHub |
| **GitHub** | `main` branch (`dayan-battulga/dayanpi`) |
| **Pi** (`dayoon`) | Runs the app at `~/Desktop/site-page/dayanpi` |

Always use the **`main`** branch on both machines.

### App URLs (paths)

| Path | Purpose |
| --- | --- |
| `/` | Dashboard |
| `/api/stats` | One JSON snapshot |
| `/api/stream` | Live SSE feed |
| `/api/health` | Health check |
| `/video` | MJPEG camera |
| `/api/drive` | Motor commands (POST, used by the Drive card) |
| `/docs` | Disabled (404 on purpose) |

### How you open it

| From | URL / method |
| --- | --- |
| **Pi itself** | http://127.0.0.1:8000/ |
| **Mac (Tailscale app on)** | https://dayoon.tail279594.ts.net/ via **Serve** |
| **Phone without Tailscale** | Same URL via **Funnel** (public internet) |
| **Home LAN IP** `http://192.168.x.x:8000` | Does **not** work (app listens on 127.0.0.1 only) |

Login is **HTTP Basic Auth** from `/etc/dayanpi.env` — not your Linux password.

---

## First-time setup (Pi)

```bash
cd ~/Desktop/site-page/dayanpi
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`--system-site-packages` lets the venv see `gpiozero` and `lgpio`, which come from apt, not pip.

### Already have a venv? Switch it over

If your `.venv` was made without that flag, you don't need to rebuild it. Just flip one line:

```bash
cd ~/Desktop/site-page/dayanpi
sed -i 's/^include-system-site-packages = false/include-system-site-packages = true/' .venv/pyvenv.cfg
grep include-system-site-packages .venv/pyvenv.cfg   # should say true
.venv/bin/python -c "import gpiozero, lgpio"         # no output = good
```

### Camera group

```bash
groups   # must include "video"
```

If missing:

```bash
sudo usermod -aG video $USER
```

Then log out and back in.

### Password file

```bash
sudo cp dayanpi.env.example /etc/dayanpi.env
sudo nano /etc/dayanpi.env
```

Set your own values (you invent these):

```
DAYANPI_USER=yourname
DAYANPI_PASSWORD=a-strong-password
```

Then:

```bash
sudo chmod 600 /etc/dayanpi.env
sudo chown root:root /etc/dayanpi.env
```

### Install systemd service

```bash
sudo cp dayanpi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dayanpi
sudo systemctl status dayanpi
```

You want `Active: active (running)`.

### Network interface

```bash
ls /sys/class/net/
```

Skip `lo`. If you use Ethernet, change `wlan0` to `eth0` in `app.py` (`RateSampler`) and redeploy.

---

## Everyday: ship code Mac → Pi

**On Mac**

```bash
cd ~/Desktop/code/projects/site-page
git add .
git commit -m "describe the change"
git push origin main
```

**On Pi**

```bash
cd ~/Desktop/site-page/dayanpi
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart dayanpi
```

If `dayanpi.service` changed:

```bash
sudo cp dayanpi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart dayanpi
```

---

## Start / stop the app (systemd)

This is the website process. **No terminal needs to stay open** for this.

| Action | Command |
| --- | --- |
| Start now | `sudo systemctl start dayanpi` |
| Stop now | `sudo systemctl stop dayanpi` |
| Restart | `sudo systemctl restart dayanpi` |
| Status | `sudo systemctl status dayanpi` |
| Start on boot | `sudo systemctl enable dayanpi` |
| Don’t start on boot | `sudo systemctl disable dayanpi` |
| Live logs | `journalctl -u dayanpi -f` |
| Last 50 lines | `journalctl -u dayanpi -n 50 --no-pager` |
| Logs this boot | `journalctl -u dayanpi -b` |

`start` / `stop` = now. `enable` / `disable` = on boot. You usually want both enabled and started.

### Dev mode (manual uvicorn)

```bash
sudo systemctl stop dayanpi
cd ~/Desktop/site-page/dayanpi
source .venv/bin/activate
export DAYANPI_USER=yourname
export DAYANPI_PASSWORD=yourpass
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

When finished: `Ctrl+C`, then `sudo systemctl start dayanpi`.

---

## Driving the rover

The **Drive** card sits right under the camera. Whatever you press gets sent to the Pi about 7 times a second, and the card shows what's going out (`L` / `R`, from -1 to +1) plus whether you're driving.

One-time check on the Pi: `groups` should include `gpio`, since the service runs as `dayoon` and needs to touch the motor pins.

### On the Mac: keyboard

Click on the page first so it has focus, then hold:

| Keys | What happens |
| --- | --- |
| `W` / `S` | Forward / backward |
| `A` / `D` | Spin left / right in place |
| `W`+`A`, `W`+`D` | Arc left / right while going forward |
| `S`+`A`, `S`+`D` | Same arcs, backing up |
| `W`+`S` or `A`+`D` | Cancel out, nothing moves |

Let go and it stops. Pressing `Cmd`, `Ctrl` or `Alt` also stops it, and so does switching apps or tabs.

### On the phone: the pad

Same idea with the four arrow buttons. Hold ▲ and ◀ with two thumbs to arc left, and so on. Lifting your thumb or sliding it off the button stops that direction. Leaving Safari or locking the phone stops everything.

If the card turns red and says `drive failed`, the Pi didn't get the command (lost signal, logged out, and so on). There are no instant retries: while you're holding a key it keeps sending at the normal pace (one request at a time), and the error clears as soon as one gets through.

### Safety

- **Watchdog.** If the Pi doesn't hear a command for 0.5 s, it stops the wheels on its own. So if your phone dies, the tab crashes or Wi-Fi drops, the robot stops about half a second later.
- **Speed cap.** The Pi never runs the motors above `MAX_SPEED` (60% power by default), no matter what the browser sends.
- **The battery switch is the real emergency stop.** Everything above is software. If the Pi crashes hard (power glitch, kernel panic), the motor pins can stay stuck on whatever they were last doing. If the robot misbehaves, flip the battery switch. Test new code with the wheels up on a box.
- Stopping or restarting the service (`sudo systemctl stop/restart dayanpi`) stops the motors cleanly first.

### Tuning

Change the numbers on the Mac, push, pull on the Pi, and restart the service.

| Knob | File | Default | What it does |
| --- | --- | --- | --- |
| `SPEED_FLOOR` | `drivetrain.py` | `0.4` | Slowest power that still turns the wheels. If gentle presses just make the motors hum, raise it. |
| `MAX_SPEED` | `drivetrain.py` | `0.6` | Top power. Raise it slowly, around 0.1 at a time. |
| `DEADZONE` | `drivetrain.py` | `0.05` | Anything smaller than this counts as zero. |
| `DRIVE_TIMEOUT_S` | `app.py` | `0.5` | How long the watchdog waits before stopping the wheels. |

About the watchdog timeout: the browser sends every 0.15 s, so the timeout has to stay well above that. If driving over Funnel or cellular feels jerky (keeps stopping and starting), the network is laggy; try `0.8`. Going lower than 0.5 makes it stop faster but stutter more.

The arc turns come from the table at the top of `static/drive.js`. `0.4` there is the inner wheel's input *before* scaling, so it ends up a bit faster than `SPEED_FLOOR`.

### "GPIO busy"

While the service runs, it owns the motor pins. If you try driving them from a Python REPL or script, you'll get "GPIO busy". Stop the service first:

```bash
sudo systemctl stop dayanpi
# ...poke at the motors...
sudo systemctl start dayanpi
```

---

## Tailscale: Serve vs Funnel

You need **two** things for remote access:

1. **`dayanpi` service** — the app on port 8000
2. **Serve or Funnel** — HTTPS proxy from Tailscale → `127.0.0.1:8000`

### Important: use `--bg`

On this Pi, plain `sudo tailscale serve 8000` shows “Press Ctrl+C to exit”. **Ctrl+C clears the config** (`tailscale serve status` → `No serve config`).

Always prefer background mode:

```bash
sudo tailscale serve --bg 8000    # private (Tailscale devices only)
sudo tailscale funnel --bg 8000   # public internet
```

Then you **can close the terminal / disconnect SSH**.

Check anytime:

```bash
tailscale serve status
sudo tailscale funnel status
sudo systemctl status dayanpi
```

### First-time Tailscale permissions

If Serve/Funnel says “not enabled” or “access denied”:

1. Open the admin link Tailscale prints (login.tailscale.com) and approve Serve/Funnel
2. Optionally: `sudo tailscale set --operator=$USER` so you need less `sudo` later

---

## Access from your Mac (private)

Tailscale app must be connected on the Mac.

```bash
sudo systemctl status dayanpi
sudo tailscale serve --bg 8000
tailscale serve status
```

Open: **https://dayoon.tail279594.ts.net/**

Log in with `/etc/dayanpi.env` credentials.

Scroll down for **CPU / Temp / Memory** charts (fill over ~2 minutes; empty right after refresh is normal).

---

## Access from iPhone without Tailscale (public Funnel)

> **Heads up: the site can drive the robot now.** With Funnel on, anyone on the internet who gets your password can move it, and the login page is out there for anyone to hammer on. For driving, use **Serve** with the Tailscale app on your phone instead (see [Alternative: Tailscale on the phone](#alternative-tailscale-on-the-phone)). It's private to your devices. Keep Funnel off unless you really need it.

Funnel puts the same hostname on the **public internet**. Only do this after Stage 7 auth is working.

Serve and Funnel both want HTTPS port 443. If you see `listener already exists for port 443`, reset first:

```bash
sudo systemctl status dayanpi
sudo tailscale serve reset
sudo tailscale funnel --bg 8000
sudo tailscale funnel status
```

You want status like:

```
Available on the internet:
https://dayoon.tail279594.ts.net/
|-- proxy http://127.0.0.1:8000
Funnel started and running in the background.
```

On the phone:

1. Open **https://dayoon.tail279594.ts.net/** (include `https://`)
2. Prefer **cellular with Wi‑Fi off** to test like a stranger
3. Enter Basic Auth when Safari prompts (refresh / Private tab if the dialog doesn’t appear)

### Turn Funnel off (kill switch)

```bash
sudo tailscale funnel --https=443 off
```

or:

```bash
sudo tailscale funnel reset
```

Anyone with the URL can reach the login page while Funnel is on. Keep the password strong.

### Alternative: Tailscale on the phone

Install the Tailscale app, join the same account, use **Serve** instead of Funnel. Stays private. **This is the recommended way to drive from the phone.**

If Funnel is currently on, switch back to Serve:

```bash
sudo tailscale funnel reset
sudo tailscale serve --bg 8000
tailscale serve status
```

---

## Can I close the terminal?

| Piece | Close terminal OK? |
| --- | --- |
| `dayanpi` (systemd) | Yes |
| `tailscale serve --bg` / `funnel --bg` | Yes |
| Foreground `tailscale serve 8000` (no `--bg`) | No — Ctrl+C / closing SSH clears Serve |

---

## Stage 7 security checklist (before Funnel)

```bash
curl -s localhost:8000/api/stats
# expect 401

curl -s -u wrong:wrong localhost:8000/video
# expect 401

curl -s -u YOURUSER:YOURPASS localhost:8000/api/stats
# expect JSON

curl -s localhost:8000/docs
# expect 404
```

Password must live in `/etc/dayanpi.env`, not in the unit file.

Also:

```bash
sudo grep -i password /etc/systemd/system/dayanpi.service
# should find nothing
```

---

## Charts

- Below the video and stats section
- Three cards: CPU · 2 min, Temp · 2 min, Memory · 2 min
- Need live SSE data — wait 10–30+ seconds for lines; ~2 minutes to fill the window
- Hard-refresh if the page was cached: `Cmd+Shift+R`
- Vendor file must exist: `ls static/vendor/uPlot.min.js`

---

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| `Unit dayanpi.service not found` | `sudo cp dayanpi.service /etc/systemd/system/` then `daemon-reload` and `enable --now` |
| `activating (auto-restart)` / crash loop | `journalctl -u dayanpi -n 50 --no-pager` |
| `No module named 'slowapi'` | `pip install -r requirements.txt` then `sudo systemctl restart dayanpi` |
| Missing env / won’t start | Create `/etc/dayanpi.env` with `DAYANPI_USER` and `DAYANPI_PASSWORD` |
| Connection refused on LAN IP:8000 | Expected — use Serve or Funnel |
| 401 everywhere | Use credentials from `/etc/dayanpi.env` |
| Port in use | `sudo lsof -i :8000` — stop leftover uvicorn or the service |
| Camera busy / black | Only one opener; restart service; confirm `video` in `groups` |
| Empty charts | Wait for SSE; hard refresh; check `static/vendor/` |
| "GPIO busy" in a REPL or script | The service owns the motor pins, so `sudo systemctl stop dayanpi` first |
| Service won't start, GPIO permission error | `groups` must include `gpio`, then restart |
| Drive card says `drive failed` | Check the service is running and you're logged in; `journalctl -u dayanpi -n 50 --no-pager` |
| Driving feels jerky (stops and starts) | Laggy network; raise `DRIVE_TIMEOUT_S` in `app.py` (see Tuning) |
| `No serve config` after Ctrl+C | Use `sudo tailscale serve --bg 8000` |
| Serve access denied | Approve in Tailscale admin; try `sudo` |
| `listener already exists for port 443` | `sudo tailscale serve reset` then `sudo tailscale funnel --bg 8000` |
| iPhone can’t open Funnel URL | Confirm Funnel status + `dayanpi` running; full `https://` URL; cellular; try Private tab |
| Mac works, phone doesn’t (no Tailscale) | Phone needs Funnel or the Tailscale app |

---

## Mental model

1. Edit on Mac → push `main`
2. Pull on Pi → `sudo systemctl restart dayanpi`
3. Proxy with `serve --bg` (private) or `funnel --bg` (public)
4. Open https://dayoon.tail279594.ts.net/ → log in
5. Leave systemd **enabled** so the app survives disconnects and reboots
6. Harden first; Funnel second — never expose an unauthenticated camera. Now that the site drives the robot, stick to Serve.
7. Funnel kill switch: `sudo tailscale funnel reset`
