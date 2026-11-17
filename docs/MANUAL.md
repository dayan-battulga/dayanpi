# dayanpi — Run Manual

Live dashboard for a Raspberry Pi 5: focus tracking, Pi stats, live updates over SSE, and a camera feed.

Everyone signs in with their own account (up to 4, invite only), and the app is bound to **localhost only**. You reach it through Tailscale: Serve for your own devices, and Funnel (the public internet) once the camera lock is set. Your full camera feeds only ever answer you, on your own Tailscale devices.

This manual covers setting up the Pi, shipping code, running the service, Tailscale, power, security and troubleshooting. Each add-on has its own guide next to it:

- [Focus tracker](focus-tracker.md): the detector check, the models, how the tracker runs and logs, the to-do list, the calendar, hand signs
- [Pi camera](pi-camera.md): the Camera Module 3 Wide instead of the USB webcam, or both at once
- [Voice](voice.md): callouts out loud through a USB speaker

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
| `/login` | The sign-in page |
| `/join/<code>` | Make an account from an invite link |
| `/settings` | Your name, password, sign out and Mac helper tokens; invites and accounts for the owner |
| `/api/login`, `/api/logout`, `/api/join` | Sign in, sign out, join with an invite (JSON only) |
| `/api/me`, `/api/me/password`, `/api/tokens` | Your account, your password, your Mac helper tokens |
| `/api/invites`, `/api/accounts` | Owner only: invites and accounts |
| `/api/stats` | One JSON snapshot (owner only) |
| `/api/stream` | Live SSE feed (members only get the focus part) |
| `/api/health` | Health check (open, no sign-in) |
| `/video` | MJPEG camera (owner only; with the camera lock on, only from your own Tailscale devices; 404 otherwise) |
| `/video/side` | MJPEG side camera, with `DAYANPI_CAMERA=both` (404 otherwise; same lock as `/video`) |
| `/api/focus` | Focus state, today's totals, timeline, and the last hand sign (`gesture`) |
| `/api/mac/app` | The Mac helper reports the front app, and the site for a browser (POST `{"app": ..., "site": ...}`; site optional, a plain host name). While Mac tracking is off it's dropped, still a 200, with `"enabled": false` |
| `/api/mac/tracking` | The dashboard's Mac tracking switch: GET `{"enabled": ...}`, or POST `{"enabled": true}` / `false` to flip it |
| `/api/todos` | The to-do list (GET), or add one (POST `{"text": ...}`) |
| `/api/todos/<id>` | Edit, check, uncheck or make current (PATCH with any of `text`, `done`, `current`), or delete (DELETE) |
| `/api/days?month=YYYY-MM` | Each day's numbers for the calendar, one month at a time (today's live) |
| `/api/days/YYYY-MM-DD` | One day's page from `data/days/` as markdown (today's built live; 404 when there's no page) |
| `/docs` | Disabled (404 on purpose) |

### How you open it

| From | URL / method |
| --- | --- |
| **Pi itself** | http://localhost:8000/ |
| **Mac or phone (Tailscale app on)** | https://dayoon.tail279594.ts.net/ via **Serve** |
| **Anyone else, once Funnel is on** | https://dayoon.tail279594.ts.net/ via **Funnel** (they need an account; no camera) |
| **Home LAN IP** `http://192.168.x.x:8000` | Does **not** work (app listens on 127.0.0.1 only) |

You sign in on the `/login` page with your dashboard username and password, not your Linux password. See [Signing in](#signing-in).

---

## First-time setup (Pi)

```bash
cd ~/Desktop/site-page/dayanpi
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`--system-site-packages` lets the venv see `picamera2`, which comes from apt, not pip.

### Already have a venv? Switch it over

If your `.venv` was made without that flag, you don't need to rebuild it. Just flip one line:

```bash
cd ~/Desktop/site-page/dayanpi
sed -i 's/^include-system-site-packages = false/include-system-site-packages = true/' .venv/pyvenv.cfg
grep include-system-site-packages .venv/pyvenv.cfg   # should say true
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

These make your owner account the first time the app starts (when there's no `data/accounts.db` yet), and that's what you sign in with. After that the app ignores them, unless `accounts.db` goes missing. It still won't start without them, though, so leave them in. Before you ever turn on Funnel, add `DAYANPI_TAILSCALE_LOGIN` too (see [Camera lock](#camera-lock)).

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

## Working on the dashboard

The page is a React app in `web/` (TypeScript, Vite, Tailwind CSS and shadcn/ui). `npm run build` turns it into plain files in `dayanpi/static/`, and those get committed, so the Pi just serves them: no Node on the Pi, nothing new to install there. Never edit `dayanpi/static/` by hand, because the next build wipes it.

**Once, on the Mac.** Install Node (the current LTS, for example `brew install node`), then:

```bash
cd ~/Desktop/code/projects/site-page/web
npm ci
cp .env.example .env.local
nano .env.local        # just the Pi's address, DAYANPI_URL
```

`.env.local` is gitignored. Only the dev server reads it, to know where the Pi is, and it never ends up in the page. There's no password in it any more: you sign in on the dev page itself. Use Chrome (or Brave, Edge, Arc) for that. The Pi's sign-in cookie is https-only, and Chrome still keeps it on plain http://localhost, but Safari throws it away, so there you'd sign in fine and then land straight back on `/login`.

**Working on it with live data:**

```bash
npm run dev
```

Open http://localhost:5173. The page is your local copy, but `/api` and `/video` go to the Pi, so you see the real numbers and the real camera. Save a file and the page updates right away.

**Tests:**

```bash
npm test
```

**Shipping it:**

```bash
npm run build          # type-checks, then rewrites dayanpi/static/
cd ..
.venv/bin/python -m pytest tests/test_app.py -q
git add web dayanpi/static
git commit -m "describe the change"
git push origin main
```

On the Pi, `git pull` is all a page-only change needs (restart too if Python changed). A normal reload picks it up, since the Pi tells browsers to check for new files every time.

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
export DAYANPI_TAILSCALE_LOGIN=you@github   # if Funnel is on, or the camera isn't locked while you test
uvicorn dayanpi.app:app --host 127.0.0.1 --port 8000 --reload
```

Keep `--host 127.0.0.1`. The camera lock trusts a header that only Tailscale gets to set, and that only holds while nothing but the Pi itself can reach port 8000.

When finished: `Ctrl+C`, then `sudo systemctl start dayanpi`.

---

## Accounts

### Signing in

Open the site and it sends you to `/login`. Sign in with your username and password. The very first time, that's the `DAYANPI_USER` / `DAYANPI_PASSWORD` from `/etc/dayanpi.env`.

- **It lasts 30 days**, and every visit pushes that back, so a device you use keeps you signed in. **Sign out** from the menu under your name at the top right (or in Settings), and that sign-in is gone on the Pi too.
- **Wrong passwords.** Five misses in a row on one username and that name has to wait 30 s. Each miss after a wait doubles it, up to 15 minutes, and the right password clears it. The message is always "wrong username or password", even during a wait, so a stranger can't tell which names exist or which are waiting. Restarting the service clears every wait. With [the camera lock](#camera-lock) on, a sign-in from your own Tailscale devices never waits and its typos don't count, so strangers on Funnel guessing your username can't keep you out; everyone else (you over Funnel too) still waits.
- **Changing your password:** Settings → Password. It asks for the current one (a wrong one counts as a sign-in miss, and after 5 wrong ones in a row it says **too many tries, wait a bit**: 30 seconds, doubling each time up to 15 minutes), and the new one needs at least 10 characters. It signs you out on every other device and keeps this one signed in. After that, the password in `/etc/dayanpi.env` doesn't work any more. It only comes back if `data/accounts.db` is gone (see [Forgot your password?](#forgot-your-password)).
- **Your name:** Settings → Display name. That's what the header shows.

All of it lives in `data/accounts.db` on the Pi (or in `DAYANPI_DATA_DIR`): accounts, sign-ins, invites and Mac helper tokens. Passwords are stored scrambled (scrypt with a salt), and sign-ins, invites and tokens only as a fingerprint (sha256), so the file holds nothing you could sign in with. None of them ever show up in the journal either.

### Inviting someone

Up to 4 accounts in all: you (the owner) plus 3 members.

1. Settings → Invites, and make one.
2. Copy the link it shows (`https://dayoon.tail279594.ts.net/join/...`) and send it to them somewhere private, because anyone with the link can use it. You only see it this once. Lost it? Delete that invite and make a new one.
3. They open it, pick a display name, a username and a password (at least 10 characters), and they're signed in. Usernames are 2 to 32 characters: lowercase letters, digits, dots, dashes and underscores, starting with a letter or digit (capitals just turn lowercase).

A link works once, for 7 days. With 4 accounts, no invite works and you can't make new ones ("the room is full"). Someone who isn't on your tailnet can only open the link once [Funnel](#funnel-the-public-internet) is on.

**What a member can do for now:** see the dashboard the way you see it (focus, timeline, to-dos, calendar, apps, the Mac line) and change their own name, password and Mac helper tokens. It's all still your data. Everyone getting their own desk is the next step.

**What a member can't do:** change anything of yours (to-dos, the Mac tracking switch and Mac reports are all a 403 for them), open the Pi page (the camera, temps, memory, disk, power), or touch invites and accounts.

**Removing someone:** Settings → Accounts. Their account, sign-ins and Mac tokens are gone right away, and a tab they still have open stops getting live updates on the spot. The owner can't be removed.

### Using the API from a terminal

`curl -u` doesn't work any more. Sign in once, keep the cookie in a file, and send it along after that. On the Pi:

```bash
python3 -c 'import getpass, json; print(json.dumps({"username": "yourname", "password": getpass.getpass()}))' \
  | (umask 077; curl -s -c ~/.dayanpi-cookies -H 'Content-Type: application/json' -d @- localhost:8000/api/login)
curl -s -b ~/.dayanpi-cookies localhost:8000/api/focus | python3 -m json.tool
```

The first command asks for your password (so it stays out of your shell history) and prints `{"user": ...}` when it worked. `~/.dayanpi-cookies` is now your sign-in for 30 days, and `umask 077` makes sure only you can read it. From the Mac it's the same with `https://dayoon.tail279594.ts.net` in place of `localhost:8000`. The cookie is https-only, but curl makes an exception for localhost, so plain `localhost:8000` works on the Pi.

- **Writes** need `-H 'Content-Type: application/json'` and a JSON body, or you get a 415 "send JSON": `curl -s -b ~/.dayanpi-cookies -H 'Content-Type: application/json' -d '{"text": "call the dentist"}' localhost:8000/api/todos`
- **With the camera lock on**, `/video` is a 404 from `localhost`, on purpose: that request never went through Tailscale.
- **Done?** `curl -s -b ~/.dayanpi-cookies -H 'Content-Type: application/json' -d '{}' localhost:8000/api/logout; rm ~/.dayanpi-cookies`

### Forgot your password?

**A member:** remove them in Settings → Accounts and send a new invite.

**You, the owner:** the only way back is a fresh `accounts.db`. That deletes every account, sign-in, invite and Mac token, so everyone else needs a new invite afterwards:

```bash
sudo systemctl stop dayanpi
cd ~/Desktop/site-page/dayanpi
old=data/accounts-old-$(date +%F-%H%M%S)
mkdir "$old" && mv data/accounts.db* "$old"/ && sudo systemctl start dayanpi
```

The old copy goes in a folder named after the date and time, so doing this a second time doesn't trip over the first one. If the last line prints an error, the app stays stopped on purpose (starting it with the old `accounts.db` would bring the old password back), so check `ls data/` and fix that first. (With `DAYANPI_DATA_DIR`, the file's in that folder instead.) On the way up, the app makes you again from `/etc/dayanpi.env`, so sign in with that password, then make a new Mac helper token (see `mac_helper/README.md`). Your focus log, to-dos and day pages aren't in `accounts.db`, so they all stay.

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

Install the Tailscale app, sign in to the same account, and keep it connected. Then open **https://dayoon.tail279594.ts.net/** and sign in (see [Signing in](#signing-in)). See [The dashboard](#the-dashboard) for what's where.

### Camera lock

Serve tags every request from your own Tailscale devices with the Tailscale login it came from (a `Tailscale-User-Login` header), and throws away any copy a client tries to send. Requests through Funnel never have it. Set `DAYANPI_TAILSCALE_LOGIN` to your login, and `/video` and `/video/side` only answer you (the owner, signed in on the page, not a Mac token) on one of your own Tailscale devices. Anything else (a member, you over Funnel, a different login) gets a 404, as if there was no camera. The Camera card says **Tailscale only** then, instead of showing a broken feed. Everything else on the page works over Funnel the same as always.

Find your login on the Pi:

```bash
tailscale status --json | python3 -c 'import json, sys; s = json.load(sys.stdin); print(s["User"][str(s["Self"]["UserID"])]["LoginName"])'
```

That's the account the Pi is signed in to, something like `you@github` or `you@gmail.com`, and it's the right one as long as your Mac and phone are signed in to that same account. If it prints `tagged-devices`, or you're not sure, the admin console's Users page (login.tailscale.com/admin/users) lists everyone's login. Copy it exactly: it's matched letter for letter, capitals too.

Put it in the env file and restart:

```bash
sudo nano /etc/dayanpi.env     # add a line: DAYANPI_TAILSCALE_LOGIN=you@github
sudo systemctl restart dayanpi
journalctl -u dayanpi -b --no-pager | grep -i tailscale
```

The journal line says the camera is locked to your login. Without the variable it warns "camera not locked to Tailscale, don't turn on Funnel" instead, and the camera works for you from anywhere, like before.

**Check it worked:** on your Mac with Tailscale on, Peek shows the camera like always. Once Funnel is on, take your phone, switch Tailscale and Wi-Fi off, open the site, sign in, open the Pi page, and the Camera card says **Tailscale only**.

### Funnel (the public internet)

Only after the camera lock is set. Funnel lets anyone on the internet reach the site. They still have to sign in, nobody gets an account without an invite, and the camera stays yours. It's also how someone who isn't on your tailnet opens an invite link.

```bash
journalctl -u dayanpi -b --no-pager | grep -i tailscale   # says locked? don't skip this
sudo tailscale funnel --bg 8000
tailscale funnel status
```

`funnel status` should show `https://dayoon.tail279594.ts.net (Funnel on)` going to `http://127.0.0.1:8000`. Like Serve, `--bg` keeps it after you close the terminal, and after reboots. If it says Funnel isn't enabled, open the link it prints and allow Funnel for the Pi, same as Serve the first time. Your own devices still come in through Serve, which is why the camera keeps working for you.

Turning it back off (Serve only):

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

1. Shut the Pi down:
   ```bash
   sudo poweroff
   ```
2. Wait for the green light to stop blinking, then unplug the Pi.

If a dashboard tab is open somewhere, `poweroff` can hang for up to about 90 s. The camera and stats streams keep the app busy until systemd gives up and force-stops it. That's harmless, just slow. Close the tabs first to avoid it.

### Turning it back on

1. Plug in the Pi (webcam already connected).
2. Wait about a minute, then open https://dayoon.tail279594.ts.net/ (you're usually still signed in). Hard-refresh if it looks stale.

### Missing something after boot?

| What you see | Check |
| --- | --- |
| Site won't load at all | `sudo systemctl status dayanpi` and `tailscale serve status` |
| Service keeps restarting | `journalctl -u dayanpi -b --no-pager \| tail -40` |
| Camera card says reconnecting | Is the webcam plugged in? It reconnects on its own once it's there, no restart needed |
| Power says `now: undervoltage` (red Undervoltage pill on the Pi page) | The supply is too weak. Undervoltage can reboot the Pi |

---

## Security checklist

On the Pi:

```bash
curl -s localhost:8000/api/stats
# expect {"detail":"sign in first"}

curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/
# expect 303 (off to /login)

curl -s -H 'Content-Type: application/json' -d '{"username":"nobody","password":"not-the-password"}' localhost:8000/api/login
# expect {"detail":"wrong username or password"}

curl -s -o /dev/null -w '%{http_code}\n' -d 'username=nobody&password=x' localhost:8000/api/login
# expect 415 (a plain form post is refused: writes have to be JSON)

journalctl -u dayanpi -b --no-pager | grep -i tailscale
# expect the camera locked to your login before Funnel goes on
```

Then sign in the way [Using the API from a terminal](#using-the-api-from-a-terminal) shows, and:

```bash
curl -s -b ~/.dayanpi-cookies localhost:8000/api/stats
# expect JSON

curl -s -o /dev/null -w '%{http_code}\n' --max-time 3 -b ~/.dayanpi-cookies localhost:8000/video
# with the camera lock on, expect 404 (localhost doesn't go through Tailscale); lock off: 200 after 3 s

curl -s -o /dev/null -w '%{http_code}\n' -b ~/.dayanpi-cookies localhost:8000/docs
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

The site is a few pages now: **Desk** at `/me` (`/` goes there too), **Pi** at `/pi` (just you), and **Settings**. The tabs, the dock on a phone and the Reconnecting chip are in [The pages](focus-tracker.md#the-pages).

- **Top bar:** the Desk / Pi tabs, the theme button, and your initial at the top right, with a menu for Settings and Sign out.
- **Members** get the Desk and Settings but no Pi tab, and `/pi` sends them back to the Desk (see [Inviting someone](#inviting-someone)).
- **Desk:** at the top, with no card around it, your state in big letters, a live timer, today's timeline from 6 am to midnight, and one line of totals (focus, phone, pickups) with the Mac line at its right: what's in front on the Mac (the site for a browser, the app otherwise), plus a small Pause/Resume for you (see [Steps 2 to 4](focus-tracker.md#steps-2-to-4-the-tracker-runs-inside-the-site)). Then the apps, the to-do list next to the apps (see [To-do list](focus-tracker.md#to-do-list)), and the calendar (see [Calendar](focus-tracker.md#calendar)).
- **Pi:** the camera and "What the Pi sees" (the detector's latest numbers for person and phone), then the Pi itself: a one-line summary ("Running smooth", "Running warm", "Power problem"...), tiles for temp, CPU (the whole chip as a number, plus one live bar per core), memory and disk, and a status bar for network, uptime, power and voice.
- **The camera starts hidden.** The page doesn't even open the video stream until you press **Peek**. Press **Hide** to close it again. Your browser remembers which one you picked.
- **Boxes over the video.** While you're peeking, whatever the last check counted gets a box: you in the state's color and a phone in orange, each with how sure the detector was. Only the box numbers travel with the stats (never a picture), nothing gets saved, and boxes older than 3 seconds disappear so they never trail behind the video. The detector checks about once a second, so the boxes glide to catch up rather than tracking every frame.
- **Two cameras.** With `DAYANPI_CAMERA=both`, the Camera card shows one feed at a time, front first, labeled Front or Side with its own boxes. The flip button next to Peek switches between them, and your browser remembers which one you picked. Only the feed you're looking at streams. "What the Pi sees" shows the best of the two cameras either way, since the detector keeps checking both. With one camera there's no flip button and the card looks the way it always has.
- **Light and dark.** The page follows your device's setting. The sun/moon button at the top right flips it, and your browser remembers that too. Colors only ever mean something: teal/orange/violet for focused/phone/away, amber and red for Pi warnings.
- **Animations** turn themselves off if your device is set to reduce motion.
- After an update a normal reload is enough: the Pi tells the browser to check for new files every time.

---

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| `Unit dayanpi.service not found` | `sudo cp deploy/dayanpi.service /etc/systemd/system/` then `daemon-reload` and `enable --now` |
| `activating (auto-restart)` / crash loop | `journalctl -u dayanpi -n 50 --no-pager` |
| `No module named ...` on start | `pip install -r requirements.txt` then `sudo systemctl restart dayanpi` |
| Missing env / won’t start | Create `/etc/dayanpi.env` with `DAYANPI_USER` and `DAYANPI_PASSWORD` (still needed after your account exists) |
| Connection refused on LAN IP:8000 | Expected — use Serve |
| "wrong username or password" | The first time, use the login from `/etc/dayanpi.env`; once you've changed it in Settings, use the new one. Five misses on one name means a wait (30 s, doubling up to 15 min) with the same message, so wait it out or restart the service. Lost it for good: [Forgot your password?](#forgot-your-password) |
| Signed in on the Pi's own browser but it keeps going back to `/login` | Use https://dayoon.tail279594.ts.net/ instead. The sign-in cookie is https-only, and not every browser makes an exception for plain http on the Pi itself |
| Dev page (`npm run dev`) signs you in, then goes straight back to `/login` | You're in Safari, which drops the https-only sign-in cookie on http://localhost. Use Chrome for the dev page |
| Camera card says **Tailscale only** | That's the [camera lock](#camera-lock): you came in through Funnel, or your device's Tailscale login isn't exactly `DAYANPI_TAILSCALE_LOGIN`. Switch Tailscale on and check the login. If both are fine, that device isn't using Tailscale's DNS, so the site's name led it to Funnel instead: turn on **Use Tailscale DNS** in the Tailscale app, and turn off Android's Private DNS or the browser's own secure DNS for it |
| Journal says `camera not locked to Tailscale` | Set `DAYANPI_TAILSCALE_LOGIN` and restart. Until then, keep Funnel off |
| `{"detail":"send JSON"}` (415) from curl | Every POST, PATCH and DELETE needs `-H 'Content-Type: application/json'` and a JSON body, `-d '{}'` if there's nothing to send |
| `{"detail":"too big"}` (413) from curl | A write has to say how big it is up front (curl's `-d` does) and stay under 64 KB. Streaming a body in (`-T -`, or anything chunked) gets this every time |
| The invite link says it doesn't work any more | It was used, it's older than 7 days, or it was deleted. Make a new one. With 4 accounts already, the room is full: remove someone first |
| Port in use | `sudo lsof -i :8000` — stop leftover uvicorn or the service |
| Camera busy / black | Only one opener; restart service; confirm `video` in `groups` |
| Camera says "Hidden while you work" | That's on purpose: press **Peek** |
| Numbers stuck on `--` | The live stream isn't connecting: check the pill at the top right says **Live**, then hard refresh |
| `No serve config` after Ctrl+C | Use `sudo tailscale serve --bg 8000` |
| Serve access denied | Approve in Tailscale admin; try `sudo` |
| `listener already exists for port 443` | An old Serve or Funnel setup has the port. `sudo tailscale funnel reset`, then `sudo tailscale serve --bg 8000` (and `sudo tailscale funnel --bg 8000` again if you want Funnel) |
| Mac works, phone doesn’t | The phone needs the Tailscale app, connected and signed in to the same account |

---

## Mental model

1. Edit on Mac → push `main`
2. Pull on Pi → `sudo systemctl restart dayanpi`
3. Proxy with `serve --bg` (private to your devices), and `funnel --bg` only once the camera lock is set
4. Open https://dayoon.tail279594.ts.net/ → sign in
5. Leave systemd **enabled** so the app survives disconnects and reboots
