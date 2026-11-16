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

Once the models are in `models/`, the site runs the detector by itself, about once a second, on the same camera frames the video feed uses. There's nothing to start. If the model files are missing it just logs a warning and the Focus card says "The detector isn't running on the Pi".

**The states**

| State | Means | Rule |
| --- | --- | --- |
| **focused** | At the desk, no phone in sight | You're seen in 2 checks in a row |
| **on phone** | Phone in hand | Phone spotted in 3 of the last 5 checks. Back to focused after 5 checks without it |
| **away** | Nobody at the desk | 10 seconds without you |
| **unknown** | Just started, or no camera frames for 30 s | |

The numbers come from the real frames (a quick glance at the phone doesn't count; walking out of frame for a second doesn't count either). They're constants at the top of `dayanpi/focus/tracker.py` if they need tuning.

**What it counts for the day:** focus time, phone time, away time, pickups (every switch into "on phone"), and your best focus streak. The day rolls over at local midnight. A restart doesn't lose the day: the service rebuilds today's totals from the log when it starts (it can lose up to 30 s).

**The Focus card** on the dashboard shows the state, a live timer, a timeline from 6 am to midnight (teal = focused, orange = phone, violet = away; it starts earlier if you were up before 6), today's totals and a **Start block** button. A work block is just a flag for now: while it's on, the sign dims to ambient and a break longer than 15 minutes gets flagged as "break over". The button, `/api/focus/block` and the both-hands gesture all flip it.

**Callouts** are the things it says (out loud once the speaker's in; always logged):

- *instant pickup*: on the phone within 60 s of sitting back down
- *late night phone*: on the phone between 1 and 5 am
- *long break*: you come back after 15+ minutes away
- *break over*: 15 minutes away during a work block
- *day done*: you leave after 10 pm (once a night, with the day's totals)

Gestures get a `gesture` line in the log too, and the both-hands gesture says "Block started." / "Block stopped."

**The log** lives in `data/focus_log/`, one file per day (`2026-10-29.jsonl`), one JSON line per event: state changes, pickups, callouts, block starts/stops, the Mac's front app, a day summary at midnight, and a `sample` line every 30 seconds with the latest detector numbers (person / phone confidence, face turn and tilt, plus the side camera's own numbers when you [run both cameras](#with-both-cameras)). Older files still have `snack` lines and `food` / `drink` / `side_food` numbers from when it tracked snacks; the restart and the stats tool just skip them. **Never frames or images.** It's gitignored. `DAYANPI_DATA_DIR` in `/etc/dayanpi.env` moves the whole data folder somewhere else.

Check it's filling up:

```bash
cd ~/Desktop/site-page/dayanpi
.venv/bin/python -m dayanpi.focus.stats            # today
.venv/bin/python -m dayanpi.focus.stats --days 7   # the week, plus focus by hour of day
tail -3 data/focus_log/$(date +%F).jsonl   # the raw lines
```

If you moved the data folder with `DAYANPI_DATA_DIR` in `/etc/dayanpi.env`, your shell doesn't see that file, so point it at the folder: `.venv/bin/python -m dayanpi.focus.stats --log-dir /your/folder/focus_log`.

**Routes** (all behind the login):

| Route | What |
| --- | --- |
| `GET /api/focus` | Current state, today's totals, the block, the last check's numbers, and today's timeline segments |
| `POST /api/focus/block` | `{"action": "start" \| "stop" \| "toggle"}` |
| `POST /api/mac/app` | `{"app": "Code"}`, sent by the Mac helper when the front app changes |

The focus status also rides along in every `/api/stream` update and in `/api/stats`, so the dashboard doesn't poll.

**The Mac helper** (`mac_helper/`) tells the Pi which app is in front on the Mac, so "focused" can later be split into coding / docs / browser / Slack. App names only, nothing else. Setup is in `mac_helper/README.md`: put the password in the Keychain, try `--once` and `--dry-run`, then install the LaunchAgent so it runs in the background. The **Mac** entry in the status bar at the bottom of the page shows the current app.

**Deploy it:**

```bash
cd ~/Desktop/site-page/dayanpi
git pull origin main
sudo systemctl restart dayanpi
journalctl -u dayanpi -n 20 --no-pager     # look for "focus tracker running"
```

Then open the site: the Focus card should flip to **focused** within a couple of seconds of you sitting down.

## With both cameras

With `DAYANPI_CAMERA=both` (setup is in [Using both cameras](pi-camera.md#using-both-cameras)) one camera faces you straight on and the other watches from the side (the webcam in front unless `DAYANPI_FRONT_CAMERA=picamera`), so it can catch what the front misses, like a phone in your lap. With one camera none of this applies, and the log lines stay the same as ever.

Every check grabs a new frame from each camera and gives each one its own full scan, so each camera's zoomed phone pass is around the person that camera sees. The two results then become one reading for the tracker:

| What | Comes from |
| --- | --- |
| People, phones | Both cameras |
| Face turn and tilt, gestures | The front camera only, because they assume the straight-on view |

What that means day to day:

- **You count as there if either camera sees you.** So **away** needs both to lose you, and someone walking through the side view can hold it off.
- **A phone either camera sees counts.** That's the point, but a false alarm from either one counts too. The cutoffs were tuned on front-view frames, so watch for pickups that didn't happen.
- **The side camera has to see you first.** It only does the zoomed phone pass when it finds a person at 0.5 or above. If it only catches part of you, a phone in your lap never gets looked at. `side_person` in the log tells you.
- **A stuck camera just drops out.** Its frames stop counting and the other camera carries on, same as a frozen camera today. With only the side camera working, you get people and phones but no face numbers or gestures. With neither, it goes to **unknown** after 30 s.
- **A dead front camera doesn't look dead.** The tracker keeps running off the side camera and the card looks normal, but gestures stop. What gives it away is the front feed stopping and `camera read failing` in the journal.

**Which camera caught it?** Sample lines gain `side_person` and `side_phone`, the side camera's own best numbers. The usual `person` and `phone` are the best of both cameras, so if `phone` is higher than `side_phone`, the front camera saw it better. If they match, the side did at least as well. No `side_` fields means the side camera gave no frame for that check. Samples only come every 30 s, so they show the long stretches, and a quick pickup can fall between them.

```bash
cd ~/Desktop/site-page/dayanpi
grep '"sample"' data/focus_log/$(date +%F).jsonl | tail -3
curl -s -u YOURUSER:YOURPASS localhost:8000/api/focus | python3 -c "import json, sys; print(json.load(sys.stdin)['last_check'])"
```

**Timing.** A scan takes about 185 ms on the Pi, so two come to about 370 ms, and a stuck camera adds up to 0.2 s while it waits for a frame. `ms` in the sample lines and "~X ms each" on the card are both scans added together. Checks still run once a second as long as a check stays under 1 s. If it reaches about 1.5 s (a hot Pi slowing itself down, say), the boxes over the video start flickering, because the page hides boxes older than 3 s. The scans use all four cores, so keep an eye on the Temp tile too.

## To-do list

The card next to the camera is one running to-do list (the LED sign preview moved to a smaller card below it). It carries over between work blocks and days.

- **Add** with the box at the top (Enter or **Add**). **Edit** by clicking an item's text: Enter or clicking somewhere else saves, Esc cancels. **Delete** with the ×.
- **Check it off** and it moves down to **Done today**, ticked and crossed out. Uncheck it and it goes back to where it was.
- **The current one.** The round button on an item makes it the one you're on (press it again to stop). It only collects time while you're **focused during a work block**, so phone time, away time and time outside a block don't count. Only one item is current at a time, and checking it off stops its clock. The time shows next to every item, in both lists.
- **Midnight.** Done shows what you finished today. At local midnight those items leave the list (the calendar step will write them into that day's page). Unfinished ones stay put.
- **Where it lives.** `data/todos.json` on the Pi (or in `DAYANPI_DATA_DIR`). Every change saves right away, written to a temp file and swapped in, so a power cut can't leave half a file. Collected time saves every 30 s, so a crash loses at most that much. If the file ever can't be read, the app moves it to `todos.json.broken` and starts empty instead of saving over it.
- **The log.** Each add, check, uncheck and change of current item writes a `todo` line to the focus log (`"action"`: `added`, `done`, `undone` or `current`) with the item's `id`, `text` and `seconds` so far. Edits and deletes aren't logged. The restart and the stats tool skip these lines.

The routes, all behind the login: `GET /api/todos` for the list, `POST /api/todos` with `{"text": ...}` to add, `PATCH /api/todos/<id>` with any of `text`, `done` and `current` to change one, and `DELETE /api/todos/<id>`. Every stats snapshot carries the list too, as `focus.todos`, which is how the card keeps up.

```bash
curl -s -u YOURUSER:YOURPASS localhost:8000/api/todos | python3 -m json.tool
cat data/todos.json
grep '"todo"' data/focus_log/$(date +%F).jsonl
```

## Gestures

You can boss the LED sign around from your chair: hold an arm up in front of the camera to flip pages, or hold both up to start or stop a work block. This uses a third model, YOLO11 nano **pose**. Instead of boxes, it finds 17 points on your body (nose, eyes, ears, shoulders, elbows, wrists, hips, knees, ankles). Gestures only look at your shoulders and wrists. The code is in `dayanpi/vision/pose.py` (runs the model) and `dayanpi/vision/gestures.py` (turns arm positions into gestures).

### Getting the pose model

Same story as the object model: the weights are a PyTorch file, so the conversion happens on the Mac. If `/tmp/yolo-export` is still around from last time, reuse it:

```bash
cd /tmp
/tmp/yolo-export/bin/python -c "from ultralytics import YOLO; YOLO('yolo11n-pose.pt').export(format='onnx', imgsz=(480, 640), opset=12, simplify=True)"
mv /tmp/yolo11n-pose.onnx ~/Desktop/code/projects/site-page/models/yolo11n-pose_480x640.onnx
```

`/tmp` gets wiped when the Mac restarts. If `/tmp/yolo-export` is gone, make it again first, then run the commands above:

```bash
python3 -m venv /tmp/yolo-export && /tmp/yolo-export/bin/pip install ultralytics onnx onnxslim onnxruntime
```

Quick check before you push. This should print `(1, 56, 6300)`:

```bash
cd ~/Desktop/code/projects/site-page
/tmp/yolo-export/bin/python -c "import cv2, numpy as np; net = cv2.dnn.readNetFromONNX('models/yolo11n-pose_480x640.onnx'); net.setInput(np.zeros((1, 3, 480, 640), np.float32)); print(net.forward().shape)"
```

That's 56 numbers (a box, a person score, then x, y and confidence for each of the 17 points) for each of the 6300 spots the model checks. Anything else means the export went sideways. Then push it like any other change:

```bash
cd ~/Desktop/code/projects/site-page
git pull origin main
git add models/yolo11n-pose_480x640.onnx
git commit -m "Add the YOLO11 nano pose model"
git push origin main
```

Like the other YOLO file, `models/yolo11n-pose_480x640.onnx` is Ultralytics' model (AGPL-3.0).

### The gestures

| Gesture | What it does | Hold it for |
| --- | --- | --- |
| Right hand up | Next page on the sign | 1 s |
| Left hand up | Previous page | 1 s |
| Both hands up | Start or stop a work block | 2 s |

- Right and left are **your** right and left. On the camera picture, your right hand is on the left side.
- "Up" means your wrist is clearly above your shoulder, by about a third of your shoulder width. Head height is plenty.
- Each hold fires once. To do it again, drop your hands for a second or two, then raise them again.
- After anything fires, nothing else fires until your hands come down. No chaining gestures with your hands still up.
- Going for both hands? Raise them together. One hand that's up alone for a full second counts as a page flip. Getting the second hand up before then cancels the flip.
- If the camera loses your wrist for one check, the hold keeps going. Two bad checks in a row and it starts over.
- Stretching with both arms up for 2 seconds counts as both hands up. If that keeps toggling your blocks, make the both-hands hold longer (see Tuning).

### Tips

- Face the camera and sit like you normally do. With both cameras on, gestures only use the front one (the webcam unless `DAYANPI_FRONT_CAMERA=picamera`).
- Keep both shoulders in the shot. No shoulders, no gestures.
- Keep the raised hand in the shot too. The camera looks down at your desk, so a hand straight up can go off the top of the picture. Head height works better.
- Hold still. The tracker only checks about once a second, so quick waves and swipes won't register.

### Tuning

All of these are at the top of `dayanpi/vision/gestures.py`. Change them on the Mac, push, pull on the Pi, and restart the service.

| Knob | Default | What it does |
| --- | --- | --- |
| `HOLD_SECONDS` | 1 s for pages, 2 s for blocks | How long you hold before it fires |
| `RAISE_MARGIN` | `0.3` | How far above your shoulder the wrist has to be, in shoulder widths. Raise it if gestures fire by accident; lower it if they're hard to trigger. |
| `MIN_KEYPOINT_CONFIDENCE` | `0.5` | How sure the model has to be about a shoulder or wrist before it counts |
| `MIN_PERSON_CONFIDENCE` | `0.5` | How sure it has to be that there's a person there at all |
| `ALLOWED_MISSES` | `1` | How many bad checks in a row a hold survives |

## Hand signs

Hold up a peace sign ✌️ and the Pi reads your to-do list out loud: "You have 3 things to do: finish the report, reply to emails, and do laundry." Only open items count, it reads the first 5 and says how many more ("…, and 3 more"), and with nothing open it says "Your to-do list is empty." The page also pops up a little note at the bottom for a few seconds ("✌️ Peace sign: reading your to-dos"), so you can tell it worked even with the speaker off. The arm gestures show one too.

It runs on two small hand models (see [Where the models come from](#where-the-models-come-from)): one finds palms in the frame, the other finds 21 joints on the hand. Same as everything else, it's the front camera only, about once a second. The code is in `dayanpi/vision/hands.py` (runs the models) and `dayanpi/vision/gestures.py` (finger rules and holds).

### Making the sign

- **Peace** = index and middle fingers up, ring and pinky folded. The thumb doesn't matter.
- A finger counts as **open** when its tip is farther from your wrist than its middle knuckle. That's distances, not directions, so a tilted hand still counts.
- Hold it for about a second. Like the arm gestures, it fires once, and you have to drop it (two checks without the sign, so about two seconds) before it fires again. One check that misses your hand doesn't break a hold.
- Hand signs and arm gestures hold separately, so a peace sign with your arm raised can do both.
- Palm toward the camera, around chest or face height, works best.

### Checking it on the Pi

- **Peek** at the camera: every hand it finds gets a gray box, labeled `peace` while you're making the sign and `hand` otherwise. No box around your hand means the models aren't seeing it, so the sign can't fire.
- The journal says whether the models loaded: `hand models found: hand signs are on`, or `no hand models (...): hand signs are off` if a file is missing. Missing files just turn signs off; everything else keeps working.
- Each sign that fires writes `gesture: peace` to the journal and a `gesture` line with `"name": "peace"` to the focus log, same as the arm gestures.
- The hand models add to each check. The camera card's "~N ms each" includes them, so you can see what they cost.

```bash
journalctl -u dayanpi -n 50 --no-pager | grep -iE "hand|gesture|would say"
grep '"gesture"' data/focus_log/$(date +%F).jsonl
```

### Adding a sign

Three lines. A finger rule in `HAND_SIGNS` in `dayanpi/vision/gestures.py` (which fingers have to be open or folded; leave a finger out to ignore it), a hold time in `HOLD_SECONDS` in the same file, and what it does in `SIGN_ACTIONS` in `dayanpi/app.py`. Add a line for the page's note in `web/src/components/shared/GestureToast.tsx` if you want nicer text than the sign's name.

### Tuning

| Knob | Where | Default | What it does |
| --- | --- | --- | --- |
| `HAND_MIN_CONFIDENCE` | `vision/hands.py` | `0.8` | How sure the hand model has to be. Lower it if you see no hand box while your hand is clearly up. |
| `PALM_MIN_CONFIDENCE` | `vision/hands.py` | `0.6` | How sure the palm finder has to be before the hand model even looks |
| `HOLD_SECONDS["peace"]` | `vision/gestures.py` | `1.0` | How long you hold it |
| `SPOKEN_MAX` | `focus/todos.py` | `5` | How many to-dos it reads before "and N more" |
