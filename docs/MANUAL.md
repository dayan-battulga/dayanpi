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
| `/` | The room: everyone's seat, built from what each person shares (see [What the room sees](#what-the-room-sees-sharing)) |
| `/login` | The sign-in page |
| `/join/<code>` | Make an account from an invite link |
| `/settings` | Profile (your name and password), Sharing (what the room sees of you), Camera (where your desk's checks come from), Voice and bedtime (your bedtime, where your peace sign speaks), Mac helper (the tracking switch and its tokens), and Room and invites for the owner |
| `/track` | Goes to the Room: the camera that used to live here is in the site now (see [A friend's camera](#a-friends-camera)) |
| `/track/test` | The camera test: is this laptop fast enough for the tracker (nothing goes to the Pi) |
| `/api/login`, `/api/logout`, `/api/join` | Sign in, sign out, join with an invite (JSON only) |
| `/api/me`, `/api/me/password`, `/api/tokens` | Your account, your password, your Mac helper tokens (at most 10 each; the 11th is a 409) |
| `/api/invites`, `/api/accounts` | Owner only: invites and accounts |
| `/api/stats` | One JSON snapshot (owner only) |
| `/api/stream` | Live SSE feed: your own desk's `focus` and everyone's seat as `room` (members don't get the Pi's numbers) |
| `/api/sharing` | Settings → Sharing: POST any of `{"focus", "todos", "history", "apps", "sites", "video", "nudges"}` as true/false; answers with all your switches and your seat as the room now sees it |
| `/people/<username>` | Someone's desk, read-only, built from what they share (yours goes to `/me`) |
| `/api/people/<username>` | That desk as JSON: their seat and only the pieces they share |
| `/api/people/<username>/picture` | Their seat's small picture as a JPEG, only while they share video, are at the desk and it's under 3 s old (404 otherwise) |
| `/api/nudge` | Nudge someone on their phone 5+ minutes: POST `{"username": ...}` (once per person every 10 minutes; 409 when they can't be nudged, 429 too soon) |
| `/api/room/hide`, `/api/room/show` | Hide an offline seat from the room, or bring it back: POST `{"username": ...}`, anyone signed in (400 for yourself; hiding someone who's here is a 409) |
| `/api/health` | Health check (open, no sign-in) |
| `/video` | MJPEG camera (owner only; with the camera lock on, only from your own Tailscale devices; 404 otherwise) |
| `/video/side` | MJPEG side camera, with `DAYANPI_CAMERA=both` (404 otherwise; same lock as `/video`) |
| `/api/focus` | Focus state, today's totals, timeline, and the last hand sign (`gesture`) |
| `/api/mac/app` | The Mac helper reports the front app, and the site for a browser (POST `{"app": ..., "site": ...}`; site optional, a plain host name). While Mac tracking is off it's dropped, still a 200, with `"enabled": false` |
| `/api/mac/tracking` | The dashboard's Mac tracking switch: GET `{"enabled": ...}`, or POST `{"enabled": true}` / `false` to flip it |
| `/api/todos` | The to-do list (GET), or add one (POST `{"text": ...}`; at most 100, open and done together, 409 past that) |
| `/api/todos/<id>` | Edit, check, uncheck or make current (PATCH with any of `text`, `done`, `current`), or delete (DELETE) |
| `/api/days?month=YYYY-MM` | Each day's numbers for the calendar, one month at a time (today's live) |
| `/api/days/YYYY-MM-DD` | One day's page from your desk's `days/` as markdown (today's built live; 404 when there's no page), plus `others`: everyone who shares focus time and history, with their minutes that day |
| `/api/track/reading` | The browser camera's numbers for one check (POST `{"person", "phone", "sign", "elapsed_ms"}`, plus `"picture"` (a 640×360 base64 JPEG) when the last answer said `send_picture`; about one a second, 429 faster; 409 when your desk is on the Pi's cameras) |
| `/api/track/pause` | The camera's Turn off (POST `{}`): your desk says paused until the next reading |
| `/api/track/source` | Settings → Camera: POST `{"source": "pi"}` (owner only) or `{"source": "browser"}`, and/or `{"picture": "pi"}` / `{"picture": "browser"}` for where your room picture comes from (owner only). Answers `{"source", "picture"}` |
| `/api/track/picture` | Owner only: your seat's picture on its own, from a browser camera that only sends the picture (POST `{"picture": <640×360 base64 JPEG or null>}`, about one a second; 409 unless Room picture from is this browser). Answers `{"state", "send_picture"}` |
| `/api/models/<name>` | The tracker's models (signed in, the four files in `models/` only) |
| `/api/voice` | Settings → Voice and bedtime: POST `{"bedtime": "23:30"}` and/or `{"output": "computer"}` (`"pi"` is owner only) |
| `/api/voice/test` | Test the voice (POST `{}`): a short line wherever your peace sign speaks. Once every 10 s per desk (429 with `Retry-After` sooner) |
| `/api/voice/clip` | Your own latest peace-sign clip as a WAV, once (gone after it's fetched or a minute), for This computer |
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

The page is a React app in `web/` (TypeScript, Vite and one plain stylesheet). `npm run build` turns it into plain files in `dayanpi/static/`, and those get committed, so the Pi just serves them: no Node on the Pi, nothing new to install there. Never edit `dayanpi/static/` by hand, because the next build wipes it.

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

- **It lasts 30 days**, and every visit pushes that back, so a device you use keeps you signed in. **Sign out** from the menu under your name at the top right (or at the bottom of the list in Settings), and that sign-in is gone on the Pi too.
- **Wrong passwords.** A miss says **Wrong username or password.**, rings the password box in red and gives the form a little shake. Five misses in a row on one username and that name has to wait 30 s: the page says **Too many tries. Try again in 0:30** in amber, counting down, with the button dimmed until it's over. Each miss after a wait doubles it, up to 15 minutes, and the right password clears it. A name that doesn't exist waits exactly the same way, so the wait doesn't tell a stranger which names are real. (The API answers 429 with a `Retry-After` header for the wait; a miss is a 401.) Restarting the service clears every wait. With [the camera lock](#camera-lock) on, a sign-in from your own Tailscale devices never waits and its typos don't count, so strangers on Funnel guessing your username can't keep you out; everyone else (you over Funnel too) still waits.
- **Lots of sign-ins from the internet.** Everyone signing in from somewhere other than your own Tailscale devices (friends over Funnel too) shares one allowance: 2 tries a second, 10 at once. Past that, the next one gets the same **Too many tries** for a second, whatever name it typed, so it gives nothing away. Your own devices never touch that allowance and check their password on a thread of their own, so a flood of strangers can't slow your sign-in down. The journal says it once a minute at most: `turned away 340 strangers' sign-ins in the last minute`.
- **Slow down.** Once you're signed in, every account (yours too) can make 5 changes a second, with 20 in a row allowed. Clicking around, the tracker's reading a second and the Mac helper never get near it; something hammering the Pi gets a 429 "slow down" with a `Retry-After`, and the journal says `write limit hit for sam` once a minute at most. Reading things is never limited. Like the waits, it's all in memory, so a restart starts everyone fresh.
- **Changing your password:** Settings → Profile. Type a new one (at least 10 characters) and it asks for the current one too, then **Save**. A wrong current one counts as a sign-in miss, and after 5 wrong ones in a row it says **too many tries, wait a bit** (30 seconds, doubling each time up to 15 minutes). It signs you out on every other device and keeps this one signed in. It also deletes your Mac helper tokens (so one made with a stolen sign-in stops working too), so make the helper a new one in Settings → Mac helper afterwards. After that, the password in `/etc/dayanpi.env` doesn't work any more. It only comes back if `data/accounts.db` is gone (see [Forgot your password?](#forgot-your-password)).
- **Your name:** Settings → Profile → Name, then **Save**. That's what the header shows.

Settings has a list of sections on the left (a row of pills at the top on a phone): **Profile**, **Sharing** (what the room sees of you), **Camera** (where your desk's checks come from), **Voice and bedtime**, **Mac helper** (the **Track apps and sites** switch, the same one as the Mac line's Pause/Resume, plus the helper's tokens), and for you **Room and invites**.

All of it lives in `data/accounts.db` on the Pi (or in `DAYANPI_DATA_DIR`): accounts, sign-ins, invites and Mac helper tokens. Passwords are stored scrambled (scrypt with a salt), and sign-ins, invites and tokens only as a fingerprint (sha256), so the file holds nothing you could sign in with. None of them ever show up in the journal either.

### Inviting someone

Up to 4 accounts in all: you (the owner) plus 3 members.

1. Settings → Room and invites, and press **New invite**.
2. Copy the link it shows (`https://dayoon.tail279594.ts.net/join/...`) and send it to them somewhere private, because anyone with the link can use it. You only see it this once. Lost it? Delete that invite and make a new one.
3. They open it, pick a name, a username and a password (at least 10 characters), and they're signed in. Usernames are 2 to 32 characters: lowercase letters, digits, dots, dashes and underscores, starting with a letter or digit (capitals just turn lowercase).

A link works once, for 7 days. With 4 accounts, no invite works and you can't make new ones ("the room is full"). A link that's used up or past its week shows **This invite expired** instead of the form, and a full room shows **The room is full**, both with a way back to sign in. Someone who isn't on your tailnet can only open the link once [Funnel](#funnel-the-public-internet) is on.

**Everyone has their own desk.** Each account gets its own focus log, to-do list, Mac tracking switch and day pages, in its own folder on the Pi: `data/users/<username>/` (yours too). A member uses theirs fully: their own to-dos, calendar and Mac line on `/me`, and their own Mac helper token reports to their desk. The Pi's cameras and the voice only feed yours; their desk gets its checks from their own laptop's camera instead ([below](#a-friends-camera)). Until that's on their desk says "No camera yet" with **Turn on camera**, and their time and apps don't count. Of everyone else they only see what each person shares ([What members see of each other](#what-members-see-of-each-other)).

**What a member can't do:** see or change anything of yours (every desk route only ever answers with their own desk), open the Pi page (the camera, temps, memory, power), or touch invites and accounts.

**Removing someone:** Settings → Room and invites, **Remove** next to their name, then **Yes, remove**. Their account, sign-ins and Mac tokens are gone right away, and a tab they still have open stops getting live updates on the spot. Their desk isn't deleted: its folder moves to `data/users/removed/<username>-<date>/` (with `-2`, `-3` if that day already has one) and stays there until you delete it yourself, so someone who later picks the same username starts with an empty desk. The owner can't be removed.

**Hiding a seat:** an offline seat (not here: no dayanpi tab open and no camera check in the last 2 minutes) gets a small × in its corner. It shows when you hover over the seat or tab to it, and on a phone or tablet it's always there, just dim. Anyone can press it, you or a member, and the seat leaves the Room for everyone, with **Undo** in the toast. It's only tidying: their account, desk, to-dos and history stay exactly as they are, their seat still counts as one of the 4 (so it never turns into an Invite seat), and their desk at `/people/<username>` still opens from a link. The seat comes back by itself the moment they're here again, so they never see themselves hidden. It's kept in their folder as `data/users/<username>/seat.json`, so a restart doesn't bring it back early, and the journal says who did it (`sam hid dayoon's seat`, `sam showed dayoon's seat`). To actually take someone out of the room, that's **Removing someone** above.

**When this first started:** the first start with everyone's own desk moved your old `data/focus_log/`, `data/todos.json`, `data/days/` and `data/mac_tracking.json` into `data/users/<your username>/`, once, and said so in the journal (`moved focus_log, todos.json, days, mac_tracking.json from ...`). It only ever moves, never copies or deletes. If something was already in both places, it moved nothing and logged an error instead, so you can sort it out by hand: `journalctl -u dayanpi --no-pager | grep "didn't move"`.

### A friend's camera

A member's desk counts time from their own laptop's camera, right inside the site: no page to keep open on its own anymore. Their video never leaves the laptop: Chrome runs the Pi's models right there and sends the Pi only numbers, about once a second, plus their seat's picture while they've turned Video on. Before the first time, it's worth having them run [the camera test](focus-tracker.md#the-camera-test-study-room-step-4-part-1) once.

What to send them:

1. Open **https://dayoon.tail279594.ts.net** in **Chrome** on the laptop and sign in. That's the Room. (Other browsers can't run the camera.)
2. On their own seat, press **Turn on camera**, and say yes when Chrome asks. The seat says **Starting…** while the models load (the first time it downloads them, about 18 MB, so that takes a few seconds), then shows their camera live with **Camera on**. Only they see that; the room sees their picture only with Video on.
3. **Keep a dayanpi tab open.** Any page works: the Room, their desk, Settings, someone else's desk. It keeps going behind other tabs and windows and with the window minimized. Closing every dayanpi tab stops it (that's a browser rule, not ours), and so do the laptop sleeping (lid closed) and Chrome quitting; 30 s later their desk says "unknown".
4. Next time they open the site, the camera comes back on by itself, as long as Chrome still allows it. Two dayanpi tabs? Only one runs the camera, and the other says **Camera on in another tab**.
5. Taking a break or done for the day: **Turn off** on their seat (or in Settings → Camera). The camera and the models stop, their desk says the camera's off, and it stays off next time until they turn it on again.
6. Long sessions: plug the laptop in. On a low battery it checks every 2 s instead of every second; Settings → Camera says so in its load line, with the time per check and memory.

If it says **Camera is blocked**: click the camera icon at the right end of Chrome's address bar, choose Allow, reload. **The camera is busy**: quit Zoom, FaceTime, Photo Booth or whatever else has it. Your own desk can use it too: Settings → Camera → This browser's camera, then Turn on camera (and back to the Pi's cameras when you're home).

### Your room picture

Only you get this one. Settings → Camera has a second pick under "Track focus with": **Room picture from**, either **The Pi's front camera** or **This browser's camera**. It starts out on whatever you track with, so nothing changes until you pick something, and it keeps following "Track focus with" until you do.

- **Tracked by the Pi, picture from this browser:** your seat gets **Turn on camera**. Clicking it starts this browser's camera for the picture only: no models load, nothing gets checked, and once a second it sends just the picture, and only while the Pi says you're working or on your phone. Keep a dayanpi tab open, like a friend's camera. Turn off stops it and leaves your tracking alone.
- **Tracked by the browser, picture from the Pi:** the browser checks you like before but stops sending its picture, and your tile comes from the front Pi camera instead. The Pi's cameras keep capturing while the browser tracks you, so they're there for that one picture a second.

The rest doesn't change: Sharing → **Video** still decides whether anyone sees it, there's no picture while you're away, and nothing goes to disk. The Pi page's full feeds don't change either. Members don't get the choice: their picture is always their own browser's.

### Her peace sign's voice

Everyone's peace sign speaks to them: their own to-dos and their own bedtime. Yours speaks on the Pi's speaker like before; a member's plays on their own computer, since the speaker's in your room. What to send her:

1. Settings → **Voice and bedtime**. Set **Bedtime** (it saves as soon as she picks a time; until then it's midnight).
2. *The peace sign speaks through* is already **This computer** (the Pi's speaker is greyed out: it's yours).
3. Press **Test the voice**. She should hear "This is how your peace sign sounds." and see it in the pill at the top.
4. From then on, a peace sign in front of her camera plays on whichever dayanpi page she has open, even behind other tabs. Clicking Turn on camera counts as the click the browser wants; after a reload that turned the camera back on by itself, she may have to click the pill's small play button once.

It needs the Pi's voice on (`DAYANPI_VOICE=piper`, [voice.md](voice.md)). With it off, the pill shows the words and nothing plays, and Settings says so.

### What the room sees (sharing)

Everyone picks what the room sees of them in Settings → **Sharing**, and the Pi sticks to it: a switched-off part never leaves the Pi for anyone else, not on the page and not through the API. Your own desk still shows you everything.

- **Status** (working, on the phone, away, and for how long) always shows.
- **Focus time**, **To-do list** and **History** start on.
- **Apps**, **Sites** and **Video** start off. Sites only counts while Apps is on. **Video** puts a small picture of you on your seat about once a second, only while you're working or on your phone: a friend's from the tracker on their laptop, yours from the front Pi camera, shrunk on the Pi ([pi-camera.md](pi-camera.md#your-seats-picture)), or from your browser if you picked that ([Your room picture](#your-room-picture)). This switch is the only place to show or hide it.
- **Nudges** starts on: others can nudge you once you've been on your phone 5 minutes (at most once every 10). Off, nobody gets the button. A nudge speaks where your peace sign does (the Pi's speaker for you, their own computer for everyone else), so it needs the Pi's voice on like the peace sign ([voice.md](voice.md)); with it off they still get the toast.

Everyone else sees what you share on your seat, in the sidebar or bottom bar on their Desk, Pi and Settings pages, in the quick peek when they tap your seat, and on your desk at `/people/<your username>`. History shows on that desk and, with focus time, as the group line in their calendar's day pages.

The preview next to the switches is your seat exactly as the others get it. The switches live in each person's folder as `data/users/<name>/sharing.json`, so a restart keeps them. More in [focus-tracker.md](focus-tracker.md#the-room-and-sharing-study-room-step-6-part-1).

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

**A member:** remove them in Settings → Room and invites and send a new invite.

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

Serve tags every request from your own Tailscale devices with the Tailscale login it came from (a `Tailscale-User-Login` header), and throws away any copy a client tries to send. Requests through Funnel never have it. Set `DAYANPI_TAILSCALE_LOGIN` to your login, and `/video` and `/video/side` only answer you (the owner, signed in on the page, not a Mac token) on one of your own Tailscale devices. Anything else (a member, you over Funnel, a different login) gets a 404, as if there was no camera. The Pi page's cameras say **Only on your own devices** then, instead of showing a broken feed. Everything else on the page works over Funnel the same as always. The seats' small pictures (Settings → Sharing → Video) are a separate thing: a 640×360 copy each person, you included, chooses to show the room. They go through Funnel to signed-in room members, and the lock doesn't touch them.

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

**Check it worked:** on your Mac with Tailscale on, Peek shows the camera like always. Once Funnel is on, do the phone test in [Check it's safe](#check-its-safe).

### Funnel (the public internet)

Funnel lets anyone on the internet reach the site, which is how friends who aren't on your tailnet get in. They still have to sign in, nobody gets an account without an invite, and your camera stays yours. **Only turn it on after the [camera lock](#camera-lock) is set.**

**Turning it on:**

```bash
journalctl -u dayanpi -b --no-pager | grep -i tailscale   # says locked? don't skip this
sudo tailscale funnel --bg 8000
tailscale funnel status
```

`funnel status` should show `https://dayoon.tail279594.ts.net (Funnel on)` going to `http://127.0.0.1:8000`. Like Serve, `--bg` keeps it after you close the terminal and after reboots. If it says Funnel isn't enabled, open the link it prints and allow Funnel for the Pi, same as Serve the first time. Your own devices still come in through Serve, which is why the camera keeps working for you.

**Turning it off** (back to Serve, only your own devices):

```bash
sudo tailscale funnel reset
sudo tailscale serve --bg 8000
tailscale serve status
```

Friends who aren't on your tailnet can't reach the site then (not even their invite link), but their accounts and desks stay, ready for next time.

#### Check it's safe

Do both every time you turn Funnel on, and after anything that touches `/etc/dayanpi.env`:

1. **The journal line.** `journalctl -u dayanpi -b --no-pager | grep -i tailscale` should say `camera locked to Tailscale login you@github` (your login). If it says `camera not locked to Tailscale, don't turn on Funnel`, turn Funnel off and set the lock first.
2. **The phone test.** On your phone, switch off **Tailscale and Wi-Fi**, so it really comes in from the internet through Funnel. Then open https://dayoon.tail279594.ts.net/:
   - You land on the sign-in page, and nothing else shows until you sign in.
   - Sign in as you. The room and your desk work like always.
   - Open the Pi page: the cameras say **Only on your own devices**, with no Peek.
   - Switch Tailscale back on and reload: Peek shows the camera again.

#### What strangers can reach

Someone who finds the address but has no account gets exactly this:

| What | What they get |
| --- | --- |
| `/login` | The sign-in page. Wrong passwords start a wait after 5 tries on a name, and all strangers together get 2 tries a second, 10 at once, before anything checks a password ([Signing in](#signing-in)) |
| `/join/<code>` | The join page. It only makes an account with a live invite code, and a made-up code is turned away straight off. It never says who's in the room or who sent the invite |
| `/api/health` | `{"status": "ok"}` |
| `/assets/...` | The page's own code, styles and fonts: the same files for everyone, nothing about anyone |

Everything else says "sign in first", or sends them to the sign-in page: the room, everyone's names and seats, the pictures, the Pi's numbers, the camera, the tracker's models. A Mac helper token only works on `/api/mac/...`, and never opens the camera.

#### What members see of each other

Everyone sees each other through the room (seats, the sidebar or bottom bar, the quick peek when they tap a seat, and someone's desk at `/people/<username>`), and the Pi only ever sends the parts that person shares in Settings → Sharing. That goes for you too: the others see you the same way, and you see them the same way.

| Their switch | What the others see |
| --- | --- |
| Always | Their name, whether they're here, focused / on the phone / away / offline, and for how long |
| Focus time (on to start) | Today's total, and on the peek and their desk, the day's bar with phone time and pickups |
| To-do list (on) | What they're working on and how many are done; the whole list on the peek and their desk |
| History (on) | This month's minutes per day and the total since they joined, on their desk. With focus time too, their minutes that day in everyone's calendar day pages |
| Apps (off) | The Mac app in front right now, and time per app today |
| Sites (off, needs Apps) | The site in front right now, YouTube time, and time per site today |
| Video (off) | The small picture on their seat, peek and desk, about once a second, only while they're working or on the phone, and never one older than 3 s |
| Nudges (on) | Whether the others get the Nudge button once they've been on the phone 5 minutes |

**Nobody else ever sees,** whatever the switches say: anyone's Settings, bedtime or voice, camera choice, Mac tokens, the peace-sign messages and nudges they got, their own calendar and day pages, or their focus log. **Only you** get the Pi page (cameras, temperature, memory, power), the full camera feeds (and only on your own Tailscale devices), invites and the accounts list.

**What's on your Pi.** Each desk is a folder on your SD card, `data/users/<username>/`: focus log, to-dos, day pages and switches. The site never shows one person's to another, but you can read those files over SSH, so it's fair to tell your friends that. The small pictures and the voice clips never touch the disk (they only live in memory, for seconds), and the journal never has anyone's to-dos, peace-sign or nudge words, pictures, audio, passwords or tokens: just usernames and what happened ("sam nudged dayoon", "peace sign on sam's desk").

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
| The picture stays dark while peeking | Is the webcam plugged in? The page keeps trying every 2 seconds, and the camera reconnects on its own once it's there, no restart needed |
| Amber **Undervoltage** warning on the Pi page | The supply is too weak. Undervoltage can reboot the Pi |

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

curl -s localhost:8000/api/health
# expect {"status":"ok"}: the one API answer a stranger gets

curl -s localhost:8000/api/people/yourname/picture
# expect {"detail":"sign in first"}: no seats or pictures without signing in

journalctl -u dayanpi --since today --no-pager | grep -iE "would say|didn't pass"
# only "would say something (N characters)" or "(N characters)": never anyone's words
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

The site is a few pages now: the **Room** at `/`, your **Desk** at `/me`, someone's desk at `/people/<username>`, **Pi** at `/pi` (just you), and **Settings**. The tabs, the dock on a phone and the Reconnecting chip are in [The pages](focus-tracker.md#the-pages).

- **Top bar:** the Room / Desk / Pi tabs, the theme button, and your initial at the top right, with a menu for Settings and Sign out.
- **Members** get the Desk and Settings but no Pi tab, and `/pi` sends them back to the Desk (see [Inviting someone](#inviting-someone)).
- **Desk:** at the top, with no card around it, your state in big letters, a live timer, today's timeline from 6 am to midnight, and one line of totals (focus, phone, pickups) with the Mac line at its right: what's in front on the Mac (the site for a browser, the app otherwise), plus a small Pause/Resume for you (see [Steps 2 to 4](focus-tracker.md#steps-2-to-4-the-tracker-runs-inside-the-site)). Then the apps, the to-do list next to the apps (see [To-do list](focus-tracker.md#to-do-list)), and the calendar (see [Calendar](focus-tracker.md#calendar)).
- **Pi:** **Cameras** first, then **The Pi**: temperature, CPU, memory and how long it's been up, each with its number rolling to the new one every second (the temperature's bar turns amber past 70° and red past 80°), and an amber **Undervoltage** warning while the power supply sags.
- **The cameras start hidden.** Each one is a tile behind a veil ("Hidden while you work"), and the page doesn't even open the video streams until you press **Peek**. Press **Hide** to close them again. Your browser remembers which one you picked.
- **Boxes over the video.** While you're peeking, whatever the last check counted gets a box: you in the state's color and a phone in orange, each with how sure the detector was. The tile takes the camera's own shape, so the whole picture shows with no bars and the boxes land on it. Only the box numbers travel with the stats (never a picture), nothing gets saved, and boxes older than 3 seconds disappear so they never trail behind the video. The detector checks about once a second, so the boxes glide to catch up rather than tracking every frame. Under the tiles, the latest readings: like `person 0.94 · no phone`, or `phone in hand 0.81` once a phone counts.
- **Two cameras.** With `DAYANPI_CAMERA=both`, the page still shows one camera at a time, with its own boxes. The **Side** / **Front** button next to Peek switches between them, your browser remembers which one you picked, and only the one showing streams. The readings are the best of the two cameras, since the detector checks both. With one camera there's no switch.
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
| "wrong username or password" | The first time, use the login from `/etc/dayanpi.env`; once you've changed it in Settings, use the new one. Five misses on one name means a wait (30 s, doubling up to 15 min): the page counts it down, so wait it out or restart the service. Lost it for good: [Forgot your password?](#forgot-your-password) |
| Signed in on the Pi's own browser but it keeps going back to `/login` | Use https://dayoon.tail279594.ts.net/ instead. The sign-in cookie is https-only, and not every browser makes an exception for plain http on the Pi itself |
| Dev page (`npm run dev`) signs you in, then goes straight back to `/login` | You're in Safari, which drops the https-only sign-in cookie on http://localhost. Use Chrome for the dev page |
| The cameras say **Only on your own devices** | That's the [camera lock](#camera-lock): you came in through Funnel, or your device's Tailscale login isn't exactly `DAYANPI_TAILSCALE_LOGIN`. Switch Tailscale on and check the login. If both are fine, that device isn't using Tailscale's DNS, so the site's name led it to Funnel instead: turn on **Use Tailscale DNS** in the Tailscale app, and turn off Android's Private DNS or the browser's own secure DNS for it |
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
