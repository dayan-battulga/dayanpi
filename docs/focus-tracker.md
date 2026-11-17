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

**The log** lives in `data/focus_log/`, one file per day (`2026-10-29.jsonl`), one JSON line per event: state changes, pickups, callouts, hand signs, the Mac's front app (and the site, for a browser), a day summary at midnight, and a `sample` line every 30 seconds with the latest detector numbers (person / phone confidence, face turn and tilt, plus the side camera's own numbers when you [run both cameras](#with-both-cameras)). Older files still have `snack` lines and `food` / `drink` / `side_food` numbers from when it tracked snacks, and `block` lines from when it had work blocks; the restart, the stats tool and the day pages just skip them. **Never frames or images.** It's gitignored. `DAYANPI_DATA_DIR` in `/etc/dayanpi.env` moves the whole data folder somewhere else.

Check it's filling up:

```bash
cd ~/Desktop/site-page/dayanpi
.venv/bin/python -m dayanpi.focus.stats            # today
.venv/bin/python -m dayanpi.focus.stats --days 7   # the week, plus focus by hour of day
tail -3 data/focus_log/$(date +%F).jsonl   # the raw lines
```

If you moved the data folder with `DAYANPI_DATA_DIR` in `/etc/dayanpi.env`, your shell doesn't see that file, so point it at the folder: `.venv/bin/python -m dayanpi.focus.stats --log-dir /your/folder/focus_log`.

**Routes** (all behind the sign-in; members can read them all, but every write in this guide is yours only for now). The `curl` lines in this guide run on the Pi and expect you to have signed in once, as in [Using the API from a terminal](MANUAL.md#using-the-api-from-a-terminal), which leaves your sign-in in `~/.dayanpi-cookies`.

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
- **It sticks.** The setting is kept in `data/mac_tracking.json` on the Pi (or in `DAYANPI_DATA_DIR`), so restarts keep it. It's on until you first switch it off.
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
| **Desk** (`/me`) | everyone | Your day: the state, timer, timeline and totals with the Mac line at the top, then apps, to-dos and the calendar. `/` takes you here until the room exists. |
| **Pi** (`/pi`) | you | The camera card and the Pi's own numbers (temp, CPU, memory, disk, power, voice). The red **Undervoltage** warning shows up here when the power supply sags. Members don't get the tab, and typing the address just lands them on their desk. |
| **Settings** (`/settings`) | everyone | Your name, password and Mac tokens, plus invites and accounts for you. |
| **Sign in**, **Join** (`/login`, `/join/<code>`) | anyone | Just the wordmark and the theme button on top. |

The frame around them:

- **The top bar:** the wordmark, the Desk / Pi tabs (the white pill slides over to the one you pick), the **⌘K** button (see below), the sun/moon button for the theme, and a round button with your initial that opens Settings and Sign out. It gets a teal ring while you're in Settings.
- **On a phone** (under 640 px wide) the tabs move into a frosted dock at the bottom: Desk, a **+** that jumps straight to the new to-do box (from any page), and Settings. The Pi page isn't in the dock yet, so on a phone open `/pi` yourself.
- **Reconnecting:** when the live stream drops (the Pi restarting, the Wi-Fi blinking), an amber **Reconnecting** chip shows next to the wordmark and the Desk and Pi pages dim until it's back. The old Live badge is gone: no chip means it's live.
- **Switching pages** cross-fades with a small rise. With Reduce motion on (on a Mac: System Settings → Accessibility → Display → Reduce motion) nothing slides: pages just fade and the tab pill jumps.
- **Toasts:** little frosted pills at the bottom right (on a phone, centered just above the dock). One at a time, gone after 4 seconds. You get one when a hand sign fires, and when the Mac tracking switch couldn't reach the Pi (the switch flips back on its own).
- **Only the Desk downloads up front.** Settings, the Pi page, sign-in, join and the ⌘K box load the first time you open them.

### ⌘K and the keyboard

Press **⌘K** (or **Ctrl+K** on Windows and Linux) anywhere, even while you're typing, or click the ⌘K button in the top bar. A box opens: start typing to narrow the list, use ↑ and ↓ to pick, **Enter** to run it, **Esc** to close. Pressing ⌘K again closes it too.

| Command | Key | Who |
| --- | --- | --- |
| Add a to-do (puts the cursor in the new to-do box on the Desk, from any page) | **N** | you |
| Go to Desk | **G** then **D** | everyone |
| Go to Pi | **G** then **P** | you |
| Go to Settings | **G** then **S** | everyone |
| Switch theme | **T** | everyone |
| Pause Mac tracking, or Resume when it's paused (same as the button on the Mac line) | | you |

The single keys only work when you're not typing in a box, so typing "n" into a to-do never jumps anywhere. For the **G** ones, press the second key within a second. A phone has no ⌘K button (it has the dock instead), but a keyboard plugged into it still opens the box.

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
grep '"sample"' data/focus_log/$(date +%F).jsonl | tail -3
curl -s -b ~/.dayanpi-cookies localhost:8000/api/focus | python3 -c "import json, sys; print(json.load(sys.stdin)['last_check'])"
```

**Timing.** A scan takes about 185 ms on the Pi, so two come to about 370 ms, and a stuck camera adds up to 0.2 s while it waits for a frame. `ms` in the sample lines and "~X ms each" on the card are both scans added together. Checks still run once a second as long as a check stays under 1 s. If it reaches about 1.5 s (a hot Pi slowing itself down, say), the boxes over the video start flickering, because the page hides boxes older than 3 s. The scans use all four cores, so keep an eye on the Temp tile too.

## To-do list

One running to-do list on the left of your desk page, under the totals, with Apps on its right (on a phone, Apps goes under it). It carries over from day to day.

- **Each row** has a checkbox, the text, the time it's collected (a dash before it has any), and a button on the right.
- **Start** makes that item the one you're on: its row gets a light tint, its time turns the state's color, and the button turns into **Working** (green, with a blinking dot) while you're focused, or **Paused** while you're on your phone or away. Click Working or Paused to stop it, so nothing's current. Only one item is current at a time, and it only collects time while you're **focused**, so phone and away time never count.
- **Next to the title:** how many are open (the number rolls when it changes), or "Start one to collect its time" when nothing's current.
- **Check it off** and it slides down into **Done**, ticked and crossed out, and the rows under it close up. Uncheck it and it slides back. Checking off the current item stops its clock.
- **Add** with the "Add a to-do" line at the bottom: type and press Enter, and the new row rises in. **N** or ⌘K's "Add a to-do" puts the cursor there from anywhere (so does the **+** in the phone dock).
- **Edit** by clicking an item's text: Enter or clicking somewhere else saves, Esc cancels.
- **Delete** with the small × just past the end of a row. With a mouse it shows when you point at the row (or Tab to it); on a phone or a touch screen it's always there, in gray.
- **It answers right away.** Every click shows up straight away, before the Pi replies. If the Pi doesn't take it (it's restarting, or the Wi-Fi blinked), the row goes back to how it was and a little toast says so. A new item shows up once the Pi has it (a moment), and if that fails your text goes back in the box.
- **Members** see the list and what's current, but get no checkboxes, buttons or add line.
- The old "Today" list of state changes is gone: the timeline at the top shows the same thing.
- **Midnight.** Done shows what you finished today. At local midnight those items leave the list, and that day's [calendar page](#calendar) keeps them. Unfinished ones stay put.
- **Where it lives.** `data/todos.json` on the Pi (or in `DAYANPI_DATA_DIR`). Every change saves right away, written to a temp file and swapped in, so a power cut can't leave half a file. Collected time saves every 30 s, so a crash loses at most that much. If the file ever can't be read, the app moves it to `todos.json.broken` and starts empty instead of saving over it.
- **The log.** Each add, check, uncheck and change of current item writes a `todo` line to the focus log (`"action"`: `added`, `done`, `undone` or `current`) with the item's `id`, `text` and `seconds` so far. Edits and deletes aren't logged. The restart and the stats tool skip these lines.

The routes, all behind the login: `GET /api/todos` for the list, `POST /api/todos` with `{"text": ...}` to add, `PATCH /api/todos/<id>` with any of `text`, `done` and `current` to change one, and `DELETE /api/todos/<id>`. Every stats snapshot carries the list too, as `focus.todos`, which is how the page keeps up.

```bash
curl -s -b ~/.dayanpi-cookies localhost:8000/api/todos | python3 -m json.tool
cat data/todos.json
grep '"todo"' data/focus_log/$(date +%F).jsonl
```

## Apps card

A bar chart of how long each Mac app was in front, right under the top of the desk. App names run down the left with the longest on top, and the time runs along the bottom in minutes (or hours once the longest bar passes 2 h). The **Today / This week** buttons pick the range (This week is the last 7 days including today), and the page remembers your pick. It refreshes every minute while the page is open. With nothing to show (or the Mac helper isn't running) it just says "Nothing from the Mac yet today".

A browser's bar has two pieces, YouTube and Other sites, so you can see how much of the browser was YouTube. Every other app is one solid bar. Hover or tap a bar for the exact time of each piece; each bar's total sits at its right end. Long app names get cut off with "..." on the chart, and the tooltip has the full name.

It counts the same way as the day page: from the 30-second sample lines, only while you're working or on your phone, the Mac isn't locked, and Mac tracking isn't switched off. Both share one counter in `focus/days.py`.

The route, behind the login: `GET /api/apps?range=today|week` (anything else is a 422). It gives `{"range", "apps"}` with the apps sorted by time, most first: the top 8, then everything else summed into one last entry called "Other apps". Each app has `total_seconds`. An app that ever had a site in the range (a browser) also has `youtube_seconds` and `other_sites_seconds`. An empty range gives `"apps": []`.

```bash
curl -s -b ~/.dayanpi-cookies "localhost:8000/api/apps?range=week" | python3 -m json.tool
```

## Calendar

Every finished day gets its own page: `data/days/YYYY-MM-DD.md` on the Pi (or in `DAYANPI_DATA_DIR`). It's plain markdown, so you can open it in anything, and the names match Obsidian's daily notes, so you can point a vault at the folder. Each page has:

- **The numbers up top, as frontmatter:** focus, phone and away minutes, pickups, best streak and how many to-dos. Obsidian shows these as properties, and the calendar card reads them back.
- **Totals:** the same numbers, readable.
- Pages written back when there were work blocks still have a **Focus blocks** section and a `blocks` number. Pages are never rewritten, so they just stay that way.
- **To-dos done:** what you checked off that day and how much time each one collected. Something you checked and then unchecked doesn't count.
- **Apps:** the top 10 Mac apps by time, from the [Mac helper](#steps-2-to-4-the-tracker-runs-inside-the-site), and in Totals, **YouTube**: the time youtube.com (or m.youtube.com, music.youtube.com) was the tab in front, in any browser. No other site is counted. Only time at the desk counts: you're working or on your phone, not away, the Mac isn't locked or asleep, and Mac tracking isn't switched off (if it was, the Apps section starts with how long it was paused). It's counted from the 30-second sample lines, so it's accurate to about half a minute. YouTube minutes are in the frontmatter too (`youtube_minutes`). Days from before apps were logged just say "None".

It's all built from that day's focus log (the to-dos come from its `todo` lines), with the same math the restart and the stats tool use.

**When pages get written.** Once when the service starts, for every past day that has a log and no page yet (that's how the old days get filled in the first time), then again a few seconds after each local midnight for the day that just ended. Like the focus checks, it waits for the network clock first. A page is never written over, so if you edit one, your edits stay. Today never gets a file; asking for today builds its page live from the log.

**The calendar card** sits under the to-do list and Apps. Each day shows its focus time and gets a darker green the more you focused (any focus, then 1 h, 2 h and 4 h and up). Today's number comes straight from the live stream, and today has an outline. Click a day to read its page under the calendar, and click it again to close it. Today's page refreshes every minute while it's open. The arrows move between months, and the top line adds up the month's focus. New pages show up within 5 minutes, so yesterday appears a few minutes after midnight.

The routes, behind the login: `GET /api/days?month=YYYY-MM` gives each day's numbers for a month (today's live), and `GET /api/days/YYYY-MM-DD` gives one day's page as `{"day", "today", "markdown"}`. The name has to be exactly digits and dashes in that shape (anything else is a 422), so it can only ever read a file from `data/days`. A day with no page is a 404.

```bash
ls data/days/
cat data/days/$(date -d yesterday +%F).md
journalctl -u dayanpi --no-pager | grep "day pages"
curl -s -b ~/.dayanpi-cookies "localhost:8000/api/days?month=$(date +%Y-%m)" | python3 -m json.tool
```

## Hand signs

Hold up a peace sign ✌️ and the Pi gives you a quick rundown out loud: the time, how long until bed, what's left on your to-do list and what you finished today. That's a fixed sentence out of the box, or a friendlier one written by a small LLM on the Pi if you set one up. Both are in [What the peace sign says](voice.md#what-the-peace-sign-says). The page also pops up a little note at the bottom for a few seconds ("✌️ Peace sign: reading your to-dos"), so you can tell it worked even with the speaker off.

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
- The hand models add to each check. The camera card's "~N ms each" includes them, so you can see what they cost.

```bash
journalctl -u dayanpi -n 50 --no-pager | grep -iE "hand|gesture|would say"
grep '"gesture"' data/focus_log/$(date +%F).jsonl
```

### Adding a sign

Three lines. A finger rule in `HAND_SIGNS` in `dayanpi/vision/gestures.py` (which fingers have to be open or folded; leave a finger out to ignore it), a hold time in `HOLD_SECONDS` in the same file, and what it does in `SIGN_ACTIONS` in `dayanpi/app.py`. Add a line for the page's toast in `web/src/hooks/useGestureToast.ts` if you want nicer text than the sign's name.

### Tuning

| Knob | Where | Default | What it does |
| --- | --- | --- | --- |
| `HAND_MIN_CONFIDENCE` | `vision/hands.py` | `0.8` | How sure the hand model has to be. Lower it if there's no `peace` box while you're clearly making the sign, or no phone box while you're holding your phone. |
| `PALM_MIN_CONFIDENCE` | `vision/hands.py` | `0.6` | How sure the palm finder has to be before the hand model even looks |
| `NEAR_HAND_MARGIN` | `vision/hands.py` | `0.25` | How close a phone has to be to a hand to count, in hand lengths. Raise it if phone time stops counting while you're holding it; lower it if a phone next to your keyboard counts. |
| `HOLD_SECONDS["peace"]` | `vision/gestures.py` | `1.0` | How long you hold it |
| `V_SPREAD` | `vision/gestures.py` | `1.8` | How wide the V has to be (fingertip gap over knuckle gap). Raise it if it still goes off by accident; lower it if a real peace sign gets no `peace` box. |
| `SPOKEN_MAX` | `focus/coach.py` | `5` | How many to-dos of each list it reads before "and N more" |
