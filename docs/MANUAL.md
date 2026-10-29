# dayanpi — Run Manual

Live dashboard for a Raspberry Pi 5: focus tracking, Pi stats, live updates over SSE, and a camera feed.

The app is password-protected and bound to **localhost only**. You reach it through Tailscale Serve, which keeps it private to your own devices. Funnel stays off: the site shows a camera pointed at you all day.

This manual covers setting up the Pi, shipping code, running the service, Tailscale, power, security and troubleshooting. Each add-on has its own guide next to it:

- [Focus tracker](focus-tracker.md): the detector check, the models, how the tracker runs and logs, gestures
- [Pi camera](pi-camera.md): the Camera Module 3 Wide instead of the USB webcam
- [LED sign](led-sign.md): the 128x32 sign's pages, wiring and bring-up
- [Voice](voice.md): callouts out loud through a USB speaker
- [Driving the rover](rover.md): paused for now; keys, safety and tuning

---

## Overview

| Machine | Role |
| --- | --- |
| **Mac** or **Claude (cloud)** | Edit code, push to GitHub |
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
| `/api/focus` | Focus state, today's totals and timeline |
| `/api/focus/block` | Start/stop a work block (POST) |
| `/api/mac/app` | The Mac helper reports the front app (POST) |
| `/api/sign/page` | Flip the LED sign to the next or previous page (POST `{"step": 1}` or `-1`) |
| `/docs` | Disabled (404 on purpose) |

### How you open it

| From | URL / method |
| --- | --- |
| **Pi itself** | http://127.0.0.1:8000/ |
| **Mac or phone (Tailscale app on)** | https://dayoon.tail279594.ts.net/ via **Serve** |
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
sudo cp deploy/dayanpi.env.example /etc/dayanpi.env
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
sudo cp deploy/dayanpi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dayanpi
sudo systemctl status dayanpi
```

You want `Active: active (running)`.

### Network interface

```bash
ls /sys/class/net/
```

Skip `lo`. If you use Ethernet, change `wlan0` to `eth0` in `dayanpi/app.py` (`RateSampler`) and redeploy.

---

## Everyday: ship code Mac → Pi

Claude pushes to `main` from the cloud too, so your Mac copy can fall behind. Pull before you edit there.

**On Mac**

```bash
cd ~/Desktop/code/projects/site-page
git pull origin main
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

If `deploy/dayanpi.service` changed:

```bash
sudo cp deploy/dayanpi.service /etc/systemd/system/
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
uvicorn dayanpi.app:app --host 127.0.0.1 --port 8000 --reload
```

When finished: `Ctrl+C`, then `sudo systemctl start dayanpi`.

---

## Tailscale Serve

You need **two** things for remote access:

1. **`dayanpi` service** — the app on port 8000
2. **Serve** — HTTPS proxy from Tailscale → `127.0.0.1:8000`, private to your own Tailscale devices

### Important: use `--bg`

On this Pi, plain `sudo tailscale serve 8000` shows “Press Ctrl+C to exit”. **Ctrl+C clears the config** (`tailscale serve status` → `No serve config`).

Always use background mode:

```bash
sudo tailscale serve --bg 8000
```

Then you **can close the terminal / disconnect SSH**. The app is systemd's job, so it doesn't need a terminal either.

Check anytime:

```bash
tailscale serve status
sudo systemctl status dayanpi
```

### First-time Tailscale permissions

If Serve says “not enabled” or “access denied”:

1. Open the admin link Tailscale prints (login.tailscale.com) and approve Serve
2. Optionally: `sudo tailscale set --operator=$USER` so you need less `sudo` later

### Opening it from your Mac or phone

Install the Tailscale app, sign in to the same account, and keep it connected. Then open **https://dayoon.tail279594.ts.net/** and log in with the `/etc/dayanpi.env` credentials. See [The dashboard](#the-dashboard) for what's where.

### Funnel stays off

Funnel would put the site on the public internet, and the site shows a camera pointed at you all day. If it ever gets turned on, this switches back to Serve:

```bash
sudo tailscale funnel reset
sudo tailscale serve --bg 8000
tailscale serve status
```

---

## Unplugging and powering back on

Everything comes back on its own after a reboot or power cut, as long as two things are switched on: the `dayanpi` service is **enabled**, and Serve was set up with **`--bg`**.

### One-time check

```bash
systemctl is-enabled dayanpi      # should say: enabled
systemctl is-enabled tailscaled   # should say: enabled
tailscale serve status            # should show https://dayoon... → proxy http://127.0.0.1:8000
```

If `dayanpi` isn't enabled: `sudo systemctl enable dayanpi`. A `--bg` Serve is saved and comes back after reboots by itself. A foreground `tailscale serve 8000` doesn't.

When it's all set, a boot goes: Pi boots → Tailscale connects → `dayanpi` starts (systemd retries every 5 s if something's not ready yet) → the site is back within about a minute.

### Turning it off

Don't just yank the plug. A sudden power cut can corrupt the SD card.

1. **Motor battery off first**, so nothing can move while the Pi shuts down.
2. Shut the Pi down:
   ```bash
   sudo poweroff
   ```
3. Wait for the green light to stop blinking, then unplug the Pi.

If a dashboard tab is open somewhere, `poweroff` can hang for up to about 90 s. The camera and stats streams keep the app busy until systemd gives up and force-stops it. That's harmless, just slow. Close the tabs first to avoid it.

### Turning it back on

1. Plug in the Pi (webcam already connected).
2. Wait about a minute, then open https://dayoon.tail279594.ts.net/ and log in. Hard-refresh if it looks stale.
3. Put the rover up on a box, then turn the motor battery on.
4. Tap `W` quickly to make sure the motors respond.

Turning the motor battery on at any point is safe. The motor pins sit low (off) during boot, and the app starts them at 0.

### Only unplugging the motor battery

- **If it only powers the motors:** the Pi and the site keep running. The wheels just won't move until the battery's back. Nothing needs a restart.
- **If it powers the Pi too:** that's a full power cut. Use the shutdown steps above next time.

### Missing something after boot?

| What you see | Check |
| --- | --- |
| Site won't load at all | `sudo systemctl status dayanpi` and `tailscale serve status` |
| Service keeps restarting | `journalctl -u dayanpi -b --no-pager \| tail -40` |
| Camera card says reconnecting | Is the webcam plugged in? It reconnects on its own once it's there, no restart needed |
| Drive card says unavailable | `journalctl -u dayanpi -b \| grep -i motors`, then check the `gpio` group and whether a script is holding the pins |
| Power says `now: undervoltage` (red Undervoltage pill up top) | The supply is too weak, especially with the motors or the sign running. Undervoltage can reboot the Pi |

---

## Security checklist

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

## The dashboard

- **Top:** the Focus card. State, a live timer, today's timeline (6 am to midnight), and today's numbers: focus, phone, pickups, time since your last pickup, snacks, best streak.
- **Middle:** the camera and "What the Pi sees" (the detector's latest numbers for person, phone, food and drink), then the LED sign preview (the dots show which page it's on) and a list of today's last few changes and snacks.
- **Bottom:** the Pi. A one-line summary ("Running smooth", "Running warm", "Power problem"...), tiles for temp, CPU (the whole chip as a number, plus one live bar per core), memory and disk, and a status bar for network, uptime, power, voice, the Mac's front app and the sign mode.
- **The camera starts hidden.** The page doesn't even open the video stream until you press **Peek**. Press **Hide** to close it again. Your browser remembers which one you picked.
- **Boxes over the video.** While you're peeking, whatever the last check counted gets a box: you in the state's color, a phone in orange, food or drink in white, each with how sure the detector was. Only the box numbers travel with the stats (never a picture), nothing gets saved, and boxes older than 3 seconds disappear so they never trail behind the video. The detector checks about once a second, so the boxes glide to catch up rather than tracking every frame.
- **Light and dark.** The page follows your device's setting. The sun/moon button at the top right flips it, and your browser remembers that too. Colors only ever mean something: teal/orange/violet for focused/phone/away, amber and red for Pi warnings.
- **Animations** turn themselves off if your device is set to reduce motion.
- Hard-refresh if the page looks old after an update: `Cmd+Shift+R`.

---

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| `Unit dayanpi.service not found` | `sudo cp deploy/dayanpi.service /etc/systemd/system/` then `daemon-reload` and `enable --now` |
| `activating (auto-restart)` / crash loop | `journalctl -u dayanpi -n 50 --no-pager` |
| `No module named ...` on start | `pip install -r requirements.txt` then `sudo systemctl restart dayanpi` |
| Missing env / won’t start | Create `/etc/dayanpi.env` with `DAYANPI_USER` and `DAYANPI_PASSWORD` |
| Connection refused on LAN IP:8000 | Expected — use Serve |
| 401 everywhere | Use credentials from `/etc/dayanpi.env` |
| Port in use | `sudo lsof -i :8000` — stop leftover uvicorn or the service |
| Camera busy / black | Only one opener; restart service; confirm `video` in `groups` |
| Camera says "Hidden while you work" | That's on purpose: press **Peek** |
| Numbers stuck on `--` | The live stream isn't connecting: check the pill at the top right says **Live**, then hard refresh |
| "GPIO busy" in a REPL or script | The service owns the motor pins, so `sudo systemctl stop dayanpi` first |
| Service won't start, GPIO permission error | `groups` must include `gpio`, then restart |
| Drive card says `drive failed` | Check the service is running and you're logged in; `journalctl -u dayanpi -n 50 --no-pager` |
| Driving feels jerky (stops and starts) | Laggy network; raise `DRIVE_TIMEOUT_S` in `dayanpi/app.py` (see the rover's [Tuning](rover.md#tuning)) |
| `No serve config` after Ctrl+C | Use `sudo tailscale serve --bg 8000` |
| Serve access denied | Approve in Tailscale admin; try `sudo` |
| `listener already exists for port 443` | Funnel is probably on: `sudo tailscale funnel reset` then `sudo tailscale serve --bg 8000` |
| Mac works, phone doesn’t | The phone needs the Tailscale app, connected and signed in to the same account |

---

## Mental model

1. Edit on Mac → push `main`
2. Pull on Pi → `sudo systemctl restart dayanpi`
3. Proxy with `serve --bg` (private to your devices)
4. Open https://dayoon.tail279594.ts.net/ → log in
5. Leave systemd **enabled** so the app survives disconnects and reboots
