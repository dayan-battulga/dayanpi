# Focus tracker

Part of the dayanpi docs. Setting up and running the Pi is in the [manual](MANUAL.md).

The webcam sits at your desk, pointed down at your face, hands and desk. The site works out whether you're **focused**, **on your phone**, or **away**, keeps today's totals, and logs every change. It's being built one step at a time; steps 1 to 4 are in.

It runs two small models on the Pi itself (nothing goes to the cloud), and they're in `models/`. They run through OpenCV, which is already installed, so there's nothing new to `pip install`.

From across the desk a phone is only a few dozen pixels, which is too small for the model to spot reliably. So each check runs the model twice: once on the whole frame to find you, then again on a zoomed-in crop around you to find the phone. That roughly doubles the time per check, which is still fine at one check a second.

## Step 1: detector check

This shows what the camera can actually pick up at your desk. The site owns the camera, so stop it while the check runs:

```bash
cd ~/Desktop/site-page/dayanpi
git pull origin main
sudo systemctl stop dayanpi
.venv/bin/python -m dayanpi.focus.check
sudo systemctl start dayanpi
```

It walks you through three 20-second phases with a 5-second countdown before each:

1. **Working:** sit and work like normal.
2. **Phone:** pick up your phone and use it like you normally would.
3. **Away:** get up and walk out of view.

About once a second it prints a line like this:

```text
[working   7s] person 0.91      | phone -    | face turn +0.04 tilt 0.47   |  212 ms
```

- **person / phone:** how sure the model is (0 to 1). `-` means it saw nothing.
- **turn:** how far your nose is left or right of center, in eye-widths. Around 0 means you're facing the camera.
- **tilt:** where your nose sits between your eyes (0) and your mouth (1). This changes when you look down.
- **ms:** how long one check took.

At the end it prints a summary table. Everything lands in `focus_check/`:

- `summary.txt`, plus one marked-up snapshot per phase (`working.jpg`, `phone.jpg`, `away.jpg`)
- `frames/`: a clean, unmarked camera frame every 2 seconds (`working_00.jpg`, `phone_03.jpg`, ...). These are for re-testing the detector off the Pi. The drawn boxes on the snapshots confuse the model, so it needs the clean ones. Each run clears out the old frames.

Want longer phases? Use `--seconds 30`.

## Getting the files to your Mac

These are photos of you and your room, so keep them out of git (`focus_check/` is in `.gitignore`, so a normal `git add .` skips them). Copy them over SSH instead. On the Mac:

```bash
scp -r dayoon@dayoon.tail279594.ts.net:~/Desktop/site-page/dayanpi/focus_check ~/Desktop/
```

(Use whatever address you normally SSH to if that one doesn't work.) Then attach `summary.txt`, the snapshots and the `frames/` files in the chat with Claude.

If it says **No camera frames**, the service is still running. Run `sudo systemctl stop dayanpi` and try again.

## Where the models come from

- `models/face_detection_yunet_2023mar.onnx` is YuNet from OpenCV's model zoo (github.com/opencv/opencv_zoo, MIT license).
- `models/yolo26n_480x640.onnx` is Ultralytics' YOLO26 nano (AGPL-3.0), converted to ONNX at 640x480 (the webcam's size; the Pi camera's 768x432 gets padded to fit). The original weights are a PyTorch file, so the conversion happens on the Mac, not the Pi. To redo it (`-U` matters if you're reusing an old `/tmp/yolo-export`: older Ultralytics doesn't know `yolo26n`):

```bash
python3 -m venv /tmp/yolo-export
/tmp/yolo-export/bin/pip install -U ultralytics onnx onnxslim onnxruntime
cd /tmp
/tmp/yolo-export/bin/python -c "from ultralytics import YOLO; YOLO('yolo26n.pt').export(format='onnx', imgsz=(480, 640), opset=12, simplify=True)"
mv /tmp/yolo26n.onnx ~/Desktop/code/projects/site-page/models/yolo26n_480x640.onnx
```

`opset=12` keeps it loadable by OpenCV's DNN module, and `imgsz=(480, 640)` means the camera frame goes in as-is, with no padding.

Quick check before you push. This should print `(1, 84, 6300)`:

```bash
cd ~/Desktop/code/projects/site-page
/tmp/yolo-export/bin/python -c "import cv2, numpy as np; net = cv2.dnn.readNetFromONNX('models/yolo26n_480x640.onnx'); net.setInput(np.zeros((1, 3, 480, 640), np.float32)); print(net.forward().shape)"
```

That's 84 numbers (a box, then a score for each of the 80 COCO classes) for each of the 6300 spots the model checks. YOLO26 can also export "NMS-free" (`nms=False`, end-to-end), which gives `(1, 300, 6)` instead. The detector can't read that one, so stick with the plain export above.

The two hand models (for the [hand signs](#hand-signs)) come ready-made, no conversion:

- `models/palm_detection_mediapipe_2023feb.onnx` is the palm detector from OpenCV's model zoo (huggingface.co/opencv/palm_detection_mediapipe, Apache 2.0), converted from Google's MediaPipe Hands.
- `models/handpose_estimation_mediapipe_2023feb.onnx` is the hand pose model from the same zoo (huggingface.co/opencv/handpose_estimation_mediapipe, Apache 2.0), also from MediaPipe Hands.

Both give the same output on OpenCV 4.12 and 5.0. To check after swapping one, this should print `[(1, 2016, 18), (1, 2016, 1)]` and then `[(1, 63), (1, 1), (1, 1), (1, 63)]`:

```bash
cd ~/Desktop/code/projects/site-page
.venv/bin/python -c "
import cv2, numpy as np
for name, size in (('palm_detection_mediapipe_2023feb', 192), ('handpose_estimation_mediapipe_2023feb', 224)):
    net = cv2.dnn.readNetFromONNX(f'models/{name}.onnx')
    net.setInput(np.zeros((1, size, size, 3), np.float32))
    print([out.shape for out in net.forward(net.getUnconnectedOutLayersNames())])
"
```

The palm model gives 2016 possible palms (a box plus 7 points on the palm, then a score for each). The hand model gives 21 joints as x, y, depth, then how sure it is there's a hand, which hand it is, and the joints again in 3D. The app only uses the first two.

## Steps 2 to 4: the tracker runs inside the site

Once the models are in `models/`, the site runs the detector by itself, about once a second, on the same camera frames the video feed uses. There's nothing to start. If the model files are missing it just logs a warning and the desk page says "The detector isn't running on the Pi" in a gray line under the totals.

**The states**

| State | Means | Rule |
| --- | --- | --- |
| **focused** | At the desk, no phone in sight | You're seen in 2 checks in a row |
| **on phone** | Phone in hand | Phone spotted in your hand in 3 of the last 5 checks. Back to focused after 5 checks without it |
| **away** | Nobody at the desk | 10 seconds without you |
| **unknown** | Just started, or no camera frames for 30 s | |

The numbers come from the real frames (a quick glance at the phone doesn't count; walking out of frame for a second doesn't count either). They're constants at the top of `dayanpi/focus/tracker.py` if they need tuning.

**Only a phone in your hand counts.** A phone lying on the desk would otherwise count as "on phone" all day, so a phone only counts when its box touches one of your hands, or comes within a quarter of a hand's length of it. The hands come from the same models as the [hand signs](#hand-signs), and each camera checks its own phones against its own hands. If the hand models are missing (or crash), phones count anywhere in the picture, like before. On the camera peek, a phone only gets a box when it counts, so a phone on the desk with no box is working as intended. The margin is `NEAR_HAND_MARGIN` in `dayanpi/vision/hands.py`.

**What it counts for the day:** focus time, phone time, away time, pickups (every switch into "on phone"), and your best focus streak. The day rolls over at local midnight. A restart doesn't lose the day: the service rebuilds today's totals from the log when it starts (it can lose up to 30 s).

**The top of your desk page** (`/me`) has no card around it, just:

- **The state, in big letters:** Focused, On your phone, Away (or Waiting while it works it out). When it changes, the old word blurs out and the new one blurs in.
- **The timer** next to it, in the state's color (teal, orange, violet): how long you've been in this state, like `42:18`, or `1:05:09` past an hour. The digits roll as they change, and it starts over at `00:00` when the state does.
- **Today's timeline** from 6 am to midnight (teal = focused, orange = phone, light violet = away). It starts earlier if you were up before 6, or if you open it before 6. The piece you're in right now is in the state's color with a slow shine on it, and the black line is now.
- **One line of totals:** "3h 12m focused · 24m on your phone · 2 pickups". The numbers roll when they change.
- **The Mac line** at the right of the totals (see [the Mac helper](#steps-2-to-4-the-tracker-runs-inside-the-site) below): "On the Mac · Code", "On the Mac · youtube.com in Google Chrome", "Mac tracking paused" or "The Mac isn't reporting". You get a small **Pause** or **Resume** next to it; members just see the line.
- **A quiet gray line** under the totals only when something's wrong: the detector isn't running, the camera isn't sending frames (so time isn't counted), or the voice can't speak (and why).

Your best streak is still counted and still on each day's page, it's just not on the Desk any more.

**Callouts** are the things it says (out loud once the speaker's in; always logged):

- *instant pickup*: on the phone within 60 s of sitting back down
- *late night phone*: on the phone between 1 and 5 am
- *long break*: you come back after 15+ minutes away
- *day done*: you leave after 10 pm (once a night, with the day's totals)

Hand signs get a `gesture` line in the log too.

**Everyone has their own desk**: their own focus log, to-do list, Mac tracking switch and day pages, all in their own folder, `data/users/<username>/` on the Pi (`focus_log/`, `todos.json`, `mac_tracking.json`, `days/`). Usernames can't change, so neither does the folder. The Pi's cameras, the voice and the peace sign only feed **your** desk (the owner's); everyone else's desk sits in "Waiting" and says "No camera on your desk yet" until their own camera comes in a later step, and their Apps stay empty until then, because apps only count while you're working or on your phone. A member's Mac helper token reports to their own desk.

**The log** lives in `data/users/<you>/focus_log/`, one file per day (`2026-10-29.jsonl`), one JSON line per event: state changes, pickups, callouts, hand signs, the Mac's front app (and the site, for a browser), a day summary at midnight, and a `sample` line every 30 seconds with the latest detector numbers (person / phone confidence, face turn and tilt, plus the side camera's own numbers when you [run both cameras](#with-both-cameras)). Older files still have `snack` lines and `food` / `drink` / `side_food` numbers from when it tracked snacks, and `block` lines from when it had work blocks; the restart, the stats tool and the day pages just skip them. **Never frames or images.** It's gitignored. `DAYANPI_DATA_DIR` in `/etc/dayanpi.env` moves the whole data folder somewhere else.

Check it's filling up (in the commands in this guide, `ME` is your username, the folder's name under `data/users/`):

```bash
cd ~/Desktop/site-page/dayanpi
ME=yourusername
.venv/bin/python -m dayanpi.focus.stats              # today, on your desk
.venv/bin/python -m dayanpi.focus.stats --days 7     # the week, plus focus by hour of day
.venv/bin/python -m dayanpi.focus.stats --user sam   # someone else's desk
tail -3 data/users/$ME/focus_log/$(date +%F).jsonl   # the raw lines
```

If you moved the data folder with `DAYANPI_DATA_DIR` in `/etc/dayanpi.env`, your shell doesn't see that file, so point it at the folder: `DAYANPI_DATA_DIR=/your/folder .venv/bin/python -m dayanpi.focus.stats`.

**Routes** (all behind the sign-in). Every desk route answers for whoever is signed in: their own focus, to-dos, days, apps and Mac tracking, and members can change their own. Only the Pi's numbers, the camera, invites and accounts are yours alone. The `curl` lines in this guide run on the Pi and expect you to have signed in once, as in [Using the API from a terminal](MANUAL.md#using-the-api-from-a-terminal), which leaves your sign-in in `~/.dayanpi-cookies`.

| Route | What |
| --- | --- |
| `GET /api/focus` | Current state, today's totals, the last check's numbers, and today's timeline segments |
| `POST /api/mac/app` | `{"app": "Google Chrome", "site": "youtube.com"}` (site optional, a plain host name or nothing), sent by the Mac helper when the front app or site changes |

The focus status also rides along in every `/api/stream` update and in `/api/stats`, so the dashboard doesn't poll.

**The Mac helper** (`mac_helper/`) tells the Pi which app is in front on the Mac, and when that's a browser, which website, so "focused" can later be split into coding / docs / browsing / Slack. Setup is in `mac_helper/README.md`: make a Mac helper token in Settings and put it in the Keychain, try `--once` and `--dry-run`, then install the LaunchAgent so it runs in the background. The **On the Mac** card at the top of the page shows what's in front, big enough to read from across the room: the site when it's a browser (`youtube.com`, with "in Google Chrome" under it), the app otherwise (`Cursor`). It's meant to let anyone walking by see what you're on. If the helper hasn't checked in for 2.5 minutes (it checks in at least once a minute, even when nothing changes), the Mac is asleep or the helper is gone, so the card says **Not reporting** and that time stops counting.

What it records, and what it never does:

- **The app's name**, like `Code` or `Google Chrome`. A locked screen is `Locked`.
- **The site, only for Google Chrome, Brave, Edge and Arc**, and only the host name without `www.`: `youtube.com`, `mail.google.com`, `localhost`. That's what goes on the `mac_app` line and every `sample` line in the focus log, next to the app.
- **Never** a full URL, a path, a query string, a page title or a window title. The helper strips everything but the host name before anything leaves the Mac, and the Pi turns away anything that isn't a plain host name.
- **Never anything from incognito or private windows.** The helper asks the browser first, and if it can't confirm the window is a normal one, it sends no site. Safari can't tell a script which windows are private, so Safari never sends a site. Firefox has nothing a script can ask, so it doesn't either.

Logs from before sites existed just have no `site`, and everything still reads them fine.

**The on/off switch.** The **Pause** button on the Mac line at the top of your desk (or ⌘K's "Pause Mac tracking") pauses Mac tracking, and **Resume** turns it back on:

- **On the Pi, right away:** reports from the helper are dropped (no log line, no current app), the current app and site are cleared, and the line says **Mac tracking paused**.
- **On the Mac, within 10 seconds:** the helper stops looking at the front app and the browser entirely, and only asks the Pi every 10 seconds whether it's back on. Flip it on and it sends the app in front straight away.
- **It sticks.** Each desk keeps its own, in `data/users/<username>/mac_tracking.json` on the Pi, so restarts keep it. It's on until you first switch it off.
- **In the log** every flip writes a `mac_tracking` line with `"enabled": true` or `false`, and while it's off, each new day starts with one too. The day page doesn't count paused time toward any site, and says how long tracking was paused. Logs from before the switch count as on.

The routes, behind the login: `GET /api/mac/tracking` gives `{"enabled": true}` or `false`, and `POST /api/mac/tracking` with `{"enabled": false}` (a real true or false, nothing else) flips it. While it's off, `POST /api/mac/app` still answers 200, with `"enabled": false` in its reply, so the helper knows to stop.

**Deploy it:**

```bash
cd ~/Desktop/site-page/dayanpi
git pull origin main
sudo systemctl restart dayanpi
journalctl -u dayanpi -n 20 --no-pager     # look for "focus tracker running"
```

Then open the site: the big word at the top should flip to **Focused** within a couple of seconds of you sitting down.

## The pages

The site is a few pages inside one frame now (the look comes from the mockups in `design/mockups`, see `design/SPEC.md`):

| Page | Who | What's on it |
| --- | --- | --- |
| **Room** (`/`) | everyone | Everyone's seat, and how long the people here have focused today together. Where you land after signing in. Tap someone's seat for the quick peek. See [The room and sharing](#the-room-and-sharing-study-room-step-6-part-1). |
| **Their desk** (`/people/<username>`) | everyone | Someone else's desk, read-only, built from what they share. Your own name takes you to your desk. See [Seeing the others](#seeing-the-others-nudges-and-the-group-calendar-study-room-step-6-part-2). |
| **Desk** (`/me`) | everyone | Your day: the state, timer, timeline and totals with the Mac line at the top, then the to-do list with Apps next to it, and the calendar. |
| **Pi** (`/pi`) | you | **Cameras**: one feed at a time (the **Side** / **Front** button switches, and only the one showing streams), hidden behind a veil until you press **Peek**, with the boxes over it and the latest readings under it. Off your own Tailscale devices they're locked. Then **The Pi**: temperature, CPU, memory and uptime, rolling to each new number. An amber **Undervoltage** warning shows up there while the power supply sags. Members don't get the tab, and typing the address just lands them on their desk. |
| **Settings** (`/settings`) | everyone | A list of sections on the left (pills on a phone): Profile (name and password), Sharing (what the room sees of you), Mac helper (the **Track apps and sites** switch, just for you, and the helper's tokens), and for you Room and invites. |
| **Sign in**, **Join** (`/login`, `/join/<code>`) | anyone | Just the wordmark and the theme button on top. |

The frame around them:

- **The top bar:** the wordmark, the Room / Desk / Pi tabs (the white pill slides over to the one you pick), on the Room a little face for everyone who's here, ringed in their state color, the **⌘K** button (see below), the sun/moon button for the theme, and a round button with your initial that opens Settings and Sign out. It gets a teal ring while you're in Settings.
- **On a phone** (under 640 px wide) the tabs move into a frosted dock at the bottom: Room, Desk, a **+** that jumps straight to the new to-do box (from any page), and Settings. The Pi page isn't in the dock yet, so on a phone open `/pi` yourself.
- **Reconnecting:** when the live stream drops (the Pi restarting, the Wi-Fi blinking), an amber **Reconnecting** chip shows next to the wordmark and the Desk and Pi pages (and the Room's seats) dim until it's back. The old Live badge is gone: no chip means it's live.
- **Switching pages** cross-fades with a small rise. With Reduce motion on (on a Mac: System Settings → Accessibility → Display → Reduce motion) nothing slides: pages just fade and the tab pill jumps.
- **Toasts:** little frosted pills at the bottom right (on a phone, centered just above the dock). One at a time, gone after 4 seconds. You get one when a hand sign other than peace fires (peace has its own pill, see [Hand signs](#hand-signs)), and when the Mac tracking switch couldn't reach the Pi (the switch flips back on its own).
- **Only the Room and the Desk download up front.** Settings, the Pi page, sign-in, join and the ⌘K box load the first time you open them.

### ⌘K and the keyboard

Press **⌘K** (or **Ctrl+K** on Windows and Linux) anywhere, even while you're typing, or click the ⌘K button in the top bar. A box opens: start typing to narrow the list, use ↑ and ↓ to pick, **Enter** to run it, **Esc** to close. Pressing ⌘K again closes it too.

| Command | Key | Who |
| --- | --- | --- |
| Add a to-do (puts the cursor in the new to-do box on the Desk, from any page) | **N** | you |
| Go to Room | **G** then **R** | everyone |
| Go to Desk | **G** then **D** | everyone |
| Go to Pi | **G** then **P** | you |
| Go to Settings | **G** then **S** | everyone |
| Switch theme | **T** | everyone |
| Pause Mac tracking, or Resume when it's paused (same as the button on the Mac line) | | you |

The single keys only work when you're not typing in a box, so typing "n" into a to-do never jumps anywhere. For the **G** ones, press the second key within a second. A phone has no ⌘K button (it has the dock instead), but a keyboard plugged into it still opens the box.

## The room and sharing (study room step 6, part 1)

`/` is the room now: a seat for each account (up to 4, two by two, two columns of smaller ones on a phone), yours first and called **You**, and an open seat for each free spot. On your open seats you get **Invite**, which opens Settings → Room and invites; a member's open seats are just empty, since only you can invite. When nobody else has an account yet it says **Just you for now** instead.

Each seat has:

- **The lamp**, a glow in their state color: teal and slowly breathing while they work, orange and quicker on the phone, none when they're away or offline.
- **Their initial** in the middle. Video comes in step 7, so for now every seat shows the initial.
- **Their name and a live timer** for how long they've been in that state. That's their status, and it always shows.
- And only what they share: **today's total** (the chip at the top left), **the current to-do** under the name (with "paused" while they aren't working on it) and **the app** after it (or "github.com in Chrome" when they share sites too; a phone's seat leaves the app off), and **the to-dos-done bar** along the bottom.

**Who's here:** anyone with the site open (the page keeps the live stream open while its tab is showing) or whose camera checked them, in the last 2 minutes. That means your desk is always here while the Pi's camera runs, away or not. Someone who isn't here gets an **offline** seat: no lamp, no timer. Up top it says how many are here and how long the people here have focused today together ("7h 05m / 3 here · focused together today"), counting only the people who share their focus time. With just you, it's your own time and "focused today".

### What each person shares

Settings → **Sharing**. Status is always on. **Focus time**, **To-do list** and **History** (your past days) start on; **Apps**, **Sites** and **Video** start off, and Sites only counts while Apps is on. Next to the switches is **What the room sees**: your seat exactly as everyone else gets it, straight from the Pi, so it changes the moment you flip something. History shows on their desk page (part 2, below); Video is the seat's small picture (step 7, below). **Nudges** (on to start) is whether others can nudge you. Your own desk always shows you everything.

### How it's enforced (for changing it)

The Pi decides, not the page. Each desk keeps its switches in `data/users/<name>/sharing.json` (`dayanpi/focus/sharing.py`), and `share_parts()` in there is the one gate everything about another person goes through: every part (a seat's to-do, their desk's apps, the day dialog's group line...) is listed in `NEEDS` with the switches it needs, and a part whose switches aren't all on is never even made. A new part that isn't in `NEEDS` is an error, so nothing new slips out without saying what it needs. Once a second the Pi builds every seat with it (`app.build_room`) and puts that in every stream event as `"room"`; `POST /api/sharing` answers with your seat built the same way, which is what the preview shows. Their desk (`GET /api/people/<username>`) and the group line on `GET /api/days/<day>` go through it too. No route hands out anyone else's whole desk.

## Seeing the others, nudges and the group calendar (study room step 6, part 2)

### Who's here, on every page

On the Desk, the Pi page and Settings, who's here sits next to your page, but only once anyone else has an account:

- **From 1280 px wide: the sidebar** ("In the room"). Each person here gets a row: their state and timer, the current to-do with its time and "paused" while they aren't working on it, the app (and site), a dot per to-do (filled when done) and today's total, each only if they share it. At the bottom: how long the people here have focused together today, and **Open the room →**. The button at the top folds it to a column of faces, and it stays folded (it's remembered in this browser).
- **Below that, down to a phone: the bottom bar**, a frosted pill along the bottom with each person here (face, name, timer, to-do, app) and a button for the room. It only shows while someone else is here.
- **On a phone** there's neither: the dock has the room.

Clicking anyone opens their desk.

### Their desk

`/people/<username>` is someone's desk, read-only, built from separate pieces, each only if they share it: **video** (their once-a-second picture, or their initial while there's none), **Today** (focus time, phone time, pickups and the timeline), **To-do**, **Apps** (with a browser's YouTube part in red when they share sites too), **Sites** and **History** (this month's calendar and how long they've focused since joining). A line at the top says what they share. When a piece is off, the rest fill the row; when they flip a switch while you watch, that piece fades in or out and the rest slide over. Their state and timer are live off the room stream; the pieces come from `GET /api/people/<username>`, asked again the moment what they share changes and every 30 s. Your own name goes to your desk.

### The quick peek

Tapping someone's seat in the room opens the quick peek: what they're working on, their day, their to-dos and today's apps (each only if they share it), **Nudge**, and **Open <name>'s desk →**.

### Nudges

Someone who's been on their phone for 5 minutes or more gets a **Nudge** button: a bell on their seat, and a button in the peek and on their desk. Press it and their speaker says "Dayan says put the phone down": the Pi's speaker for you (where your peace sign speaks), their own computer for anyone else, the same way their peace sign plays (step 5). They get a toast with it, two rings leave their seat for everyone in the room to see, and you get a "Nudged Sam" toast. A person can only be nudged once every 10 minutes, by anyone; until then the button stays greyed and says how long is left. Anyone can turn **Nudges** off in Settings → Sharing, and then the button doesn't show for them at all. The Pi checks all of this again (`POST /api/nudge`): yourself is a 400, not on the phone 5 minutes or nudges off a 409, too soon a 429 with Retry-After. Nudges are kept in memory, so a restart forgets the last one.

### The seats' small pictures (study room step 7)

With **Video** on (it starts off for everyone), your seat shows a small picture of you, about once a second, while you're working or on your phone. Away or unknown, there's no picture, just your initial. Each new frame fades in over the last one, so it feels like a calm live photo rather than video. Your own seat has a **Hide my video** / **Show my video** button at the top right (not on a phone), the same switch as Settings → Sharing → Video. The quick peek shows it in the person's face, their desk in its camera tile, and Settings' preview in your seat.

Where the picture comes from:

- **A friend's laptop:** the tracker (`/track`) shrinks its camera to a 320×180 JPEG and sends it with its next reading, but only while the Pi's last answer said `send_picture` (Video on and at the desk). The tracker page says so under the preview while it's sending.
- **Your desk on the Pi's cameras:** the Pi takes the front camera's latest frame once a second, cuts it to 16:9 and shrinks it to 320×180 (`focus/pictures.py`). Your full feeds (`/video`, `/video/side`, the Pi page's peek) don't change and stay behind the camera lock; this is a separate small copy that only exists while you've turned Video on. See [pi-camera.md](pi-camera.md#your-seats-picture).

What the Pi enforces (the page can't get around any of it):

- It keeps only the latest picture per person, in memory (`Desk.picture`), never on disk, and drops it the moment Video goes off, the tracker pauses, or a reading says away or unknown.
- A picture that arrives with Video off, or away, is dropped. Anything that isn't a real JPEG under 640×360 and 32 KB is dropped too, and the reading still counts.
- `GET /api/people/<username>/picture` goes through the same gate as everything else (`share_parts`, the `picture` part needs Video): it answers only while they share video, are at the desk and the picture is at most 3 s old, otherwise a plain 404. It's signed-in only, like every `/api/` route, and `no-store`. The room stream only says when there's a new one (`picture: {at}`), and the page fetches each frame once.

**How big:** 320×180 at JPEG quality 50 came out at 6.0–6.9 KB on real desk frames (6.6 KB on average, 8.8 KB as base64 in a reading). One person watching the room with four pictures takes about 26 KB/s, and each tracking laptop sends about 9 KB/s. If all four of you have the Room open at once, the Pi sends about 106 KB/s and takes in about 26 KB/s.

### The group calendar

A day's page in the calendar gets a quiet line at the bottom with how long everyone else focused that day ("Also focused: Sam 1h 48m · Alex 2h 5m"), only from people who share both focus time and history, and only those who focused at all.

## With both cameras

With `DAYANPI_CAMERA=both` (setup is in [Using both cameras](pi-camera.md#using-both-cameras)) one camera faces you straight on and the other watches from the side (the webcam in front unless `DAYANPI_FRONT_CAMERA=picamera`), so it can catch what the front misses, like a phone in your lap. With one camera none of this applies, and the log lines stay the same as ever.

Every check grabs a new frame from each camera and gives each one its own full scan, so each camera's zoomed phone pass is around the person that camera sees. The two results then become one reading for the tracker:

| What | Comes from |
| --- | --- |
| People, phones | Both cameras (each camera's phones only count near that camera's own view of your hands) |
| Face turn and tilt, hand signs | The front camera only, because they assume the straight-on view |

What that means day to day:

- **You count as there if either camera sees you.** So **away** needs both to lose you, and someone walking through the side view can hold it off.
- **A phone in your hand that either camera sees counts.** That's the point, but a false alarm from either one counts too. With the hand models in, the side camera has to see your hand on the phone too. The cutoffs were tuned on front-view frames, so watch for pickups that didn't happen.
- **The side camera has to see you first.** It only does the zoomed phone pass when it finds a person at 0.5 or above. If it only catches part of you, a phone in your lap never gets looked at. `side_person` in the log tells you.
- **A stuck camera just drops out.** Its frames stop counting and the other camera carries on, same as a frozen camera today. With only the side camera working, you get people and phones but no face numbers or hand signs. With neither, it goes to **unknown** after 30 s.
- **A dead front camera doesn't look dead.** The tracker keeps running off the side camera and the card looks normal, but hand signs stop. What gives it away is the front feed stopping and `camera read failing` in the journal.

**Which camera caught it?** Sample lines gain `side_person` and `side_phone`, the side camera's own best numbers. The usual `person` and `phone` are the best of both cameras, so if `phone` is higher than `side_phone`, the front camera saw it better. If they match, the side did at least as well. No `side_` fields means the side camera gave no frame for that check. Samples only come every 30 s, so they show the long stretches, and a quick pickup can fall between them.

```bash
cd ~/Desktop/site-page/dayanpi
grep '"sample"' data/users/$ME/focus_log/$(date +%F).jsonl | tail -3
curl -s -b ~/.dayanpi-cookies localhost:8000/api/focus | python3 -c "import json, sys; print(json.load(sys.stdin)['last_check'])"
```

**Timing.** A scan takes about 185 ms on the Pi, so two come to about 370 ms, and a stuck camera adds up to 0.2 s while it waits for a frame. `ms` in the sample lines and "~X ms each" on the card are both scans added together. Checks still run once a second as long as a check stays under 1 s. If it reaches about 1.5 s (a hot Pi slowing itself down, say), the boxes over the video start flickering, because the page hides boxes older than 3 s. The scans use all four cores, so keep an eye on the Temp tile too.

## To-do list

One running to-do list on the left of your desk page, under the totals, with Apps on its right (on a phone, Apps goes under it). It carries over from day to day.

- **Each row** has a checkbox, the text, the time it's collected (a dash before it has any), and a button on the right.
- **Start** makes that item the one you're on: its row gets a light tint, its time turns the state's color, and the button turns into **Working** (green, with a blinking dot) while you're focused, or **Paused** while you're on your phone or away. Click Working or Paused to stop it, so nothing's current. Only one item is current at a time, and it only collects time while you're **focused**, so phone and away time never count.
- **Next to the title:** how many are open (the number rolls when it changes), or "Start one to collect its time" when nothing's current.
- **Check it off** and it slides down into **Done**, ticked and crossed out, and the rows under it close up. Uncheck it and it slides back. Checking off the current item stops its clock.
- **All done.** Check off the last open item and a burst of confetti falls over the list once, and "All done. Nice." shows in green until you add another one (or uncheck one). Not when the page opens on a finished list, not when the list was empty to begin with, and not when you delete the last one. With Reduce motion on there's no confetti, just the line.
- **Add** with the "Add a to-do" line at the bottom: type and press Enter, and the new row rises in. **N** or ⌘K's "Add a to-do" puts the cursor there from anywhere (so does the **+** in the phone dock).
- **Edit** by clicking an item's text: Enter or clicking somewhere else saves, Esc cancels.
- **Delete** with the small × just past the end of a row. With a mouse it shows when you point at the row (or Tab to it); on a phone or a touch screen it's always there, in gray.
- **It answers right away.** Every click shows up straight away, before the Pi replies. If the Pi doesn't take it (it's restarting, or the Wi-Fi blinked), the row goes back to how it was and a little toast says so. A new item shows up once the Pi has it (a moment), and if that fails your text goes back in the box.
- **Members** see the list and what's current, but get no checkboxes, buttons or add line.
- The old "Today" list of state changes is gone: the timeline at the top shows the same thing.
- **Midnight.** Done shows what you finished today. At local midnight those items leave the list, and that day's [calendar page](#calendar) keeps them. Unfinished ones stay put.
- **Where it lives.** `data/users/<username>/todos.json` on the Pi: everyone has their own list. Every change saves right away, written to a temp file and swapped in, so a power cut can't leave half a file. Collected time saves every 30 s, so a crash loses at most that much. If the file ever can't be read, the app moves it to `todos.json.broken` and starts empty instead of saving over it.
- **The log.** Each add, check, uncheck and change of current item writes a `todo` line to the focus log (`"action"`: `added`, `done`, `undone` or `current`) with the item's `id`, `text` and `seconds` so far. Edits and deletes aren't logged. The restart and the stats tool skip these lines.

The routes, all behind the login: `GET /api/todos` for the list, `POST /api/todos` with `{"text": ...}` to add, `PATCH /api/todos/<id>` with any of `text`, `done` and `current` to change one, and `DELETE /api/todos/<id>`. Every stats snapshot carries the list too, as `focus.todos`, which is how the page keeps up.

```bash
curl -s -b ~/.dayanpi-cookies localhost:8000/api/todos | python3 -m json.tool
cat data/users/$ME/todos.json
grep '"todo"' data/users/$ME/focus_log/$(date +%F).jsonl
```

## Apps

Next to the to-do list (under it on a phone): one row per Mac app with how long it was in front, longest first, and a thin bar under each one. The longest app's bar is full width and the rest are their share of it. A browser's bar starts with its YouTube time in red, and its time says so too, like "58m · 11m YouTube". It's the top 8 apps, plus "Other apps" for everything else. The bars grow in when the page loads and when you switch ranges.

**Today** and **Week** pick the range (Week is the last 7 days including today), and the page remembers your pick. It refreshes every minute while the page is open. With nothing to show (or the Mac helper isn't running) it just says "Nothing from the Mac yet today".

It counts the same way as the day page: from the 30-second sample lines, only while you're working or on your phone, the Mac isn't locked, and Mac tracking isn't switched off. Both share one counter in `focus/days.py`.

The route, behind the login: `GET /api/apps?range=today|week` (anything else is a 422). It gives `{"range", "apps"}` with the apps sorted by time, most first: the top 8, then everything else summed into one last entry called "Other apps". Each app has `total_seconds`. An app that ever had a site in the range (a browser) also has `youtube_seconds` and `other_sites_seconds`. An empty range gives `"apps": []`.

```bash
curl -s -b ~/.dayanpi-cookies "localhost:8000/api/apps?range=week" | python3 -m json.tool
```

## Calendar

Every finished day gets its own page, on every desk: `data/users/<username>/days/YYYY-MM-DD.md` on the Pi. It's plain markdown, so you can open it in anything, and the names match Obsidian's daily notes, so you can point a vault at the folder. Each page has:

- **The numbers up top, as frontmatter:** focus, phone and away minutes, pickups, best streak and how many to-dos. Obsidian shows these as properties, and the calendar reads them back.
- **Totals:** the same numbers, readable.
- Pages written back when there were work blocks still have a **Focus blocks** section and a `blocks` number. Pages are never rewritten, so they just stay that way.
- **To-dos done:** what you checked off that day and how much time each one collected. Something you checked and then unchecked doesn't count.
- **Apps:** the top 10 Mac apps by time, from the [Mac helper](#steps-2-to-4-the-tracker-runs-inside-the-site), and in Totals, **YouTube**: the time youtube.com (or m.youtube.com, music.youtube.com) was the tab in front, in any browser. No other site is counted. Only time at the desk counts: you're working or on your phone, not away, the Mac isn't locked or asleep, and Mac tracking isn't switched off (if it was, the Apps section starts with how long it was paused). It's counted from the 30-second sample lines, so it's accurate to about half a minute. YouTube minutes are in the frontmatter too (`youtube_minutes`). Days from before apps were logged just say "None".

It's all built from that day's focus log (the to-dos come from its `todo` lines), with the same math the restart and the stats tool use.

**When pages get written.** Once when the service starts, for every past day that has a log and no page yet (that's how the old days get filled in the first time), then again a few seconds after each local midnight for the day that just ended. Like the focus checks, it waits for the network clock first. A page is never written over, so if you edit one, your edits stay. Today never gets a file; asking for today builds its page live from the log.

**The calendar** sits under the to-do list and Apps, with the month's name and its total focus on top ("November · 41h 42m focused"). Each day shows its focus time and gets a darker green the more you focused (any focus, then 1 h, 2 h and 4 h and up). Today's number comes straight from the live stream, and today has an outline. The arrows move between months. New pages show up within 5 minutes, so yesterday appears a few minutes after midnight.

Click a day and its page opens in a popup: the totals (focused, phone, away), the to-dos you finished that day with their time, and the apps. Esc, the ×, or a click outside closes it. Today works too, built live, and it refreshes every minute while it's open.

The routes, behind the login: `GET /api/days?month=YYYY-MM` gives each day's numbers for a month (today's live), and `GET /api/days/YYYY-MM-DD` gives one day's page as `{"day", "today", "markdown", "others"}` (others is the group line's names and minutes). The name has to be exactly digits and dashes in that shape (anything else is a 422), so it can only ever read a file from your own desk's `days/`. A day with no page is a 404.

```bash
ls data/users/$ME/days/
cat data/users/$ME/days/$(date -d yesterday +%F).md
journalctl -u dayanpi --no-pager | grep "day pages"
curl -s -b ~/.dayanpi-cookies "localhost:8000/api/days?month=$(date +%Y-%m)" | python3 -m json.tool
```

## Hand signs

Hold up a peace sign ✌️ and the Pi gives you a quick rundown out loud: the time, how long until bed, what's left on your to-do list and what you finished today. That's a fixed sentence out of the box, or a friendlier one written by a small LLM on the Pi if you set one up. Both are in [What the peace sign says](voice.md#what-the-peace-sign-says). The page shows what it's saying in a frosted pill under the top bar while it talks (6 seconds with the speaker off), so you can tell it worked and read along. See [What the page shows while it talks](voice.md#what-the-page-shows-while-it-talks).

It runs on two small hand models (see [Where the models come from](#where-the-models-come-from)): one finds palms in the frame, the other finds 21 joints on the hand. Signs only come from the front camera, about once a second. (The hand models also look at the side camera's frame, but only for the [phone-in-hand check](#steps-2-to-4-the-tracker-runs-inside-the-site).) The code is in `dayanpi/vision/hands.py` (runs the models) and `dayanpi/vision/gestures.py` (finger rules and holds).

### Making the sign

- **Peace** = index and middle fingers up and spread into a V, ring and pinky folded. The thumb doesn't matter.
- A finger counts as **open** when its tip is farther from your wrist than its middle knuckle. That's distances, not directions, so a tilted hand still counts.
- The **V** matters: the two fingertips have to be at least 1.8 times as far apart as the two knuckles they grow from. Two fingers side by side, like on a mouse or resting on your cheek, don't count.
- Hold it for about a second. It fires once, and you have to drop it (two checks without the sign, so about two seconds) before it fires again. One check that misses your hand doesn't break a hold.
- Palm toward the camera, around chest or face height, works best.

### Checking it on the Pi

- **Peek** at the camera: a hand making a sign gets a box labeled `peace` (front camera only, since that's where signs fire). A plain hand gets no box. No `peace` box while you're holding the sign means the models aren't reading it.
- The journal says whether the models loaded: `hand models found: hand signs are on`, or `no hand models (...): hand signs are off` if a file is missing. Missing files just turn signs off; everything else keeps working.
- Each sign that fires writes `gesture: peace` to the journal and a `gesture` line with `"name": "peace"` to the focus log.
- The hand models add to each check. `last_check.elapsed_ms` in `/api/focus` includes them, so you can see what they cost.

```bash
journalctl -u dayanpi -n 50 --no-pager | grep -iE "hand|gesture|would say"
grep '"gesture"' data/users/$ME/focus_log/$(date +%F).jsonl
```

### Adding a sign

Three lines. A finger rule in `HAND_SIGNS` in `dayanpi/vision/gestures.py` (which fingers have to be open or folded; leave a finger out to ignore it), a hold time in `HOLD_SECONDS` in the same file, and what it does in `SIGN_ACTIONS` in `dayanpi/app.py`. The page shows a new sign in a toast with its name (`web/src/hooks/useGestureToast.ts`); peace is the one that gets the pill instead.

### Tuning

| Knob | Where | Default | What it does |
| --- | --- | --- | --- |
| `HAND_MIN_CONFIDENCE` | `vision/hands.py` | `0.8` | How sure the hand model has to be. Lower it if there's no `peace` box while you're clearly making the sign, or no phone box while you're holding your phone. |
| `PALM_MIN_CONFIDENCE` | `vision/hands.py` | `0.6` | How sure the palm finder has to be before the hand model even looks |
| `NEAR_HAND_MARGIN` | `vision/hands.py` | `0.25` | How close a phone has to be to a hand to count, in hand lengths. Raise it if phone time stops counting while you're holding it; lower it if a phone next to your keyboard counts. |
| `HOLD_SECONDS["peace"]` | `vision/gestures.py` | `1.0` | How long you hold it |
| `V_SPREAD` | `vision/gestures.py` | `1.8` | How wide the V has to be (fingertip gap over knuckle gap). Raise it if it still goes off by accident; lower it if a real peace sign gets no `peace` box. |
| `SPOKEN_MAX` | `focus/coach.py` | `5` | How many to-dos of each list it reads before "and N more" |

## The camera test (study room step 4, part 1)

Before anyone else's desk gets a tracker, we need to know their laptop can run the Pi's models in Chrome, once a second, without cooking itself, and keep doing it when the tab isn't in front. `/track/test` measures exactly that. Nothing from it reaches the Pi: no frames, no numbers. The numbers stay on the page until they press **Copy** and send them to you.

### How they run it

1. Turn on Funnel if they're not on your tailnet (see the [manual](MANUAL.md)), and send them an invite from Settings.
2. They sign in on a laptop, in **Chrome** (it needs Chrome's camera-frame reader; Safari and Firefox get a "needs Chrome" line), and open **https://dayoon.tail279594.ts.net/track/test**. Typing the address matters: the page needs a full page load to get its headers, so there's no link to it from the other pages yet.
3. **Start the test**, allow the camera. The first visit downloads the three models (about 18 MB) and keeps them in the browser, so the next visit doesn't.
4. **Speed**, about 4 minutes: each way the browser can run the models gets a minute of one check a second, with the tab in front. They just sit at the desk like normal.
5. **In the background**, about 11 minutes, if they have the time: press Start, then follow the steps on the page (tab in front for a minute, another tab for 6 minutes, minimized for 2, then **Pop out** and another app for 2), then **Stop**. Six minutes on another tab is on purpose: Chrome slows hidden pages down harder after 5.
6. **Copy**, and send it to you. The results box fills in as it goes, so they can copy after the speed part if they're out of time.

If the camera's blocked, missing or busy in another app, the page says which and offers Start again. Clearing the site's data in Chrome removes the kept models.

### What the numbers mean

**Speed**, one line per way of running the models:

- **WebGPU** runs them on the graphics chip. **WASM, N threads** on N processor cores at once (that needs the page's special headers, so "isolated: yes" on the second line). **WASM, 1 thread** on one core: the slowest, but it works everywhere.
- **median / slowest**: how long one whole check took (grabbing the frame, YOLO on the whole frame, then with someone there the zoomed phone pass, the palm model and a hand model per palm), counted after 3 warm-up checks. **first scan** is the very first one, with WebGPU's setup in it.
- **late N of 60**: checks that started over 1.25 s after the one before. A check that takes longer than a second pushes the next one back.
- **no frame**: checks where the camera hadn't sent a new picture. The very first check is often one (the camera's still waking up); more than that means the camera stalls.
- **person seen**: how often it saw someone at 0.5 or more. They sat there the whole time, so it should be close to 100%. If one way says much less than the others, that way computes something wrong; don't use it.
- **memory**: the page and its workers, from Chrome. The graphics chip's own memory isn't in it.

**Fast enough** means, for the best way on the list:

| | Good | Workable | Not yet |
| --- | --- | --- | --- |
| median | under 300 ms | 300 to 600 ms (fans, battery) | over 600 ms |
| slowest | under 1 s | | over 1 s more than once |
| late | 0 to 2 of 60 | | more than 3 |
| memory | under 300 MB | | over 1 GB |

For comparison, a recent Mac in headless Chrome came out at 103 ms (WebGPU), 133 ms (4 threads) and 328 ms (1 thread), 51 to 88 MB.

**In the background**, two copies run at once with the fastest way: one on a **page timer** (the plain way: a timer on the page) and one on a **worker timer** (the timer lives in a background worker). Each line is a stretch of time in one place, in order, so for someone who followed the steps that's: tab in front, other tab, tab in front, minimized, tab in front, popped out. ("Other tab" and "minimized" both show as *other tab or minimized*; Chrome can't tell them apart.)

- **gap median / longest**: time between checks. About 1.00 s is perfect. The tracker copes with up to about 2 s; at 30 s with no check it gives up and says "unknown".
- **late**: gaps over 1.25 s.
- **no frame** in a hidden stretch means Chrome stopped sending camera frames to a hidden page. That would sink background tracking whichever timer we pick.

What we're looking for: one of the two timers holding about 1 s everywhere, with no "no frame" in the hidden stretches. The page timer slowing down while hidden is expected (Chrome throttles hidden pages' timers); that's why the worker timer is there.

### If it isn't fast enough

In rough order of how cheap they are:

1. **Run the hand models less.** They run on every check that sees someone (the palm model, then a hand model per palm), but phones only need them when the zoomed pass found a phone, and the peace sign survives one missed check. Running them only then, or every other check, takes out most of a check.
2. **Check every 2 seconds.** The rules count checks, so the phone rule would need 3 of the last 5 to mean 10 s instead of 5. Still fine for a study tracker.
3. **Smaller models**: YOLO at 320x240, or the models quantized to int8 for WASM. Both mean re-measuring accuracy on real desk frames first, like step 1 did.
4. If only the background part fails: the real tracker uses whichever timer held up. If frames stop while hidden, the pop-out window (or a pinned tab in front) becomes part of the setup.

### How it works (for changing it)

- `GET /api/models/<name>` serves the four ONNX files in `models/` (signed in, read-only, cached for a year). Nothing else in that folder is reachable. A changed model needs a new file name, because browsers keep the old one.
- The `/track/` pages get `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp`, which is what gives WASM its threads. Files under `/assets/` get the embedder header too, because a worker inside an isolated page only starts when its own script says so; other pages ignore it there. An isolated page refuses anything from another site, which is fine: everything it loads comes off the Pi.
- The browser runs the same pipeline as the Pi, ported to TypeScript in `web/src/lib/vision/`: `detector.ts`, `hands.ts`, `gestures.ts`, and `worker.ts` (the per-frame part of `focus/worker.py`), with `image.ts` standing in for the few OpenCV calls. Same constants, same steps. The face model isn't ported: the tracker only logs its turn and tilt, and nothing reads them. ONNX Runtime Web runs the models, from npm (pinned to one exact version, so the 29.5 MB WASM file in `dayanpi/static/assets/` only changes when we upgrade on purpose), and only the workers load it, never a page.
- **The port is checked against the Pi's code.** `.venv/bin/python -m dayanpi.vision.export_fixture` runs made-up model outputs, boxes and hands through the Python and saves what comes out to `web/src/lib/vision/python-fixture.json`; the TypeScript tests (`npm test`) run the same inputs and have to match. Change anything in `dayanpi/vision/` and `tests/test_vision_fixture.py` fails until you re-run the export, and then `npm test` tells you what the TypeScript side needs.
- Each way of running the models gets its own worker (ONNX Runtime fixes its thread count once it starts). Camera frames get to the workers through Chrome's `MediaStreamTrackProcessor`, and like the Pi, a frame is never scanned twice.

## The tracker (study room step 4, part 2)

`/track` is the real thing: a member's laptop camera feeds their own desk the same way the Pi's cameras feed yours. Their state, today's totals, the timeline, the to-do time, the calendar and the day pages all work exactly like yours, because the Pi runs their numbers through the same tracker.

**Only numbers leave the laptop.** The video stays in the browser (the preview says "Only you see this"). Each check sends the Pi what the tracker reads from a check: how sure it is there's a person, the best phone near a hand, the hand sign it saw (or none) and how long the check took. That's `POST /api/track/reading`, about once a second, for the sender's own desk only.

### How someone starts tracking

[MANUAL.md](MANUAL.md#a-friends-camera-the-tracker) has the steps to send them. In short: Chrome, **https://dayoon.tail279594.ts.net/track**, **Allow camera**, keep the tab open. Their desk's line under the stats says "No camera yet... Open the tracker" with a link until the first readings arrive.

### Where a desk's checks come from

Settings → **Camera**: "This desk's Pi cameras" or "This browser's camera".

- Only your desk can pick the Pi's cameras. A member's is always the browser (the Pi radio is greyed out, and the route says 403 if they try anyway).
- Your desk starts on the Pi's cameras. Pick the browser and the Pi's worker stops scanning (no detector runs at all) and your desk takes `/track`'s readings instead, from any computer. Pick the Pi again and it's back.
- Readings only count for a desk set to the browser. Your desk on the Pi gets a 409 ("this desk uses the Pi's cameras"), and `/track` says so, with a button to Settings.
- The pick is saved in each desk's folder as `camera_source.json`.

### What the Pi does with a reading

- It turns the numbers into the same reading its own cameras make (a person and a phone at those confidences) and runs it through that desk's tracker. Same rules, same log lines, same to-do time. `tests/test_browser_camera.py` checks that a run of browser readings and the same run of Pi readings end in the same states, segments and totals.
- **The hand sign hold is the Pi's**, one per desk, so the page sends the sign it saw and the Pi decides when it fires (held 1 s, like yours). A peace sign on a member's desk is a `gesture` line in their log, and the pill shows on their own page with the to-do message (the template one). Nobody hears it yet: the speaker is in your room, so saying it out loud comes in step 5.
- **Nothing coming in for 30 s means "unknown"**, like a stuck camera: once a second the Pi gives every browser desk that heard nothing for 1.5 s a check without a frame. A closed laptop or a closed tab ends up there.
- **Pause** on `/track` stops the camera and the models, and tells the Pi. The desk goes to "unknown" right away (not after 30 s) and says "Tracking is paused on the tracker page" until the next reading.
- **Every value is checked.** Person and phone must be 0 to 1, the time 0 to 60,000 ms, the sign one the Pi knows, and any other field (a picture, say) is a 422. More than about one a second is a 429: it allows one a second in the long run and two close together, so one late reading and the next on-time one both get through.

### Keeping it light

It runs for hours on someone's laptop, so it does as little as it can:

- **WebGPU** when the laptop has it (part 1's fastest), otherwise WASM on 2 threads. One session per model, made once.
- **Nobody there:** once nobody's been seen for 10 s it checks every 3 s, and goes back to every second on the first check that sees someone. The zoomed phone pass and the hand models only run on checks that see someone (with nobody there there's no phone to keep and no sign to read).
- **Struggling:** if at least half the checks over a minute took over 600 ms or started late, or the battery is under 20% and unplugged, it checks every 2 s, and goes back after a good minute. The tracker's rules cope with gaps that size (a gap counts up to 5 s).
- The line under the preview says what it's doing: time per check, memory, which way it runs the models, and why it's checking less often when it is.
- **In the background**, part 1 showed the timer in a worker kept one check a second in a hidden tab, minimized and popped out, while a timer on the page fell to every 2 s when hidden. So the checks run on the worker's own timer, and the worker sends the readings itself. There's no Pop out button: the worker didn't need it.

### What it costs (measured)

A 30-minute run on a Mac (M2 Pro) in headless Chrome, with a fake camera looping 40 s at the desk, 25 s away and 15 s on the phone:

| | |
| --- | --- |
| time per check | about 100 to 130 ms with someone there (WebGPU), 40 to 65 ms with nobody (just the one YOLO pass) |
| checks | 1,535 in 30 min, every one answered; gaps: median 1.00 s, 9 in 10 under 1.03 s, the longest 3.2 s (nobody there) |
| memory | 52 MB at the start, 45 MB at the end, never over 52 MB: no leak |
| CPU | about half of one core for all of Chrome, the preview and the video decoding included |

The `/track/test` results this was built on (127 ms a check with WebGPU) say a laptop like that comes out about the same; run the test on a new laptop first. Headless Chrome counts every tab as in front, so the hidden-tab part of this run proves nothing; part 1's real Chrome run (the worker's timer held 1.00 s hidden, minimized and popped out) is the evidence for that.

### How it works (for changing it)

- Page: `web/src/components/track/TrackPage.tsx` (Track.dc.html's ask, running and blocked steps, plus paused and the other camera problems). Worker: `tracker.worker.ts`, which shares the frame reader and the model sessions with the camera test's worker through `workerKit.ts`. The pace rules are `web/src/lib/trackPace.ts`, the messages and the load line `web/src/lib/track.ts`.
- Pi: `dayanpi/focus/browser_camera.py` (the rate limit, the pause, the desk's own sign hold, and the ticks), `dayanpi/focus/camera_source.py` (the saved pick), and the routes in `app.py`: `POST /api/track/reading`, `POST /api/track/pause` and `POST /api/track/source`, all in `MEMBER_WRITES`.
- `/track` gets the same isolation headers as `/track/test`.

