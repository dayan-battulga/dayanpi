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
.venv/bin/python scripts/focus_check.py
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
- `models/yolo11n_480x640.onnx` is Ultralytics' YOLO11 nano (AGPL-3.0), converted to ONNX at the camera's 640x480 size. The original weights are a PyTorch file, so the conversion happens on the Mac, not the Pi. To redo it:

```bash
python3 -m venv /tmp/yolo-export
/tmp/yolo-export/bin/pip install ultralytics onnx onnxslim onnxruntime
cd /tmp
/tmp/yolo-export/bin/python -c "from ultralytics import YOLO; YOLO('yolo11n.pt').export(format='onnx', imgsz=(480, 640), opset=12, simplify=True)"
mv /tmp/yolo11n.onnx ~/Desktop/code/projects/site-page/models/yolo11n_480x640.onnx
```

`opset=12` keeps it loadable by OpenCV's DNN module, and `imgsz=(480, 640)` means the camera frame goes in as-is, with no padding.

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

**What it counts for the day:** focus time, phone time, away time, pickups (every switch into "on phone"), snacks (food spotted in 3 of 5 checks; one snack per sitting), and your best focus streak. The day rolls over at local midnight. A restart doesn't lose the day: the service rebuilds today's totals from the log when it starts (it can lose up to 30 s).

**The Focus card** on the dashboard shows the state, a live timer, a timeline from 6 am to midnight (teal = focused, orange = phone, violet = away; it starts earlier if you were up before 6), today's totals and a **Start block** button. A work block is just a flag for now: while it's on, the sign dims to ambient and a break longer than 15 minutes gets flagged as "break over". The button, `/api/focus/block` and the both-hands gesture all flip it.

**Callouts** are the things it says (out loud once the speaker's in; always logged):

- *instant pickup*: on the phone within 60 s of sitting back down
- *late night phone*: on the phone between 1 and 5 am
- *long break*: you come back after 15+ minutes away
- *break over*: 15 minutes away during a work block
- *day done*: you leave after 10 pm (once a night, with the day's totals)
- *snack*: sign and log only, when a snack starts ("Snack number 2.")

Gestures get a `gesture` line in the log too, and the both-hands gesture says "Block started." / "Block stopped."

**The log** lives in `data/focus_log/`, one file per day (`2026-10-29.jsonl`), one JSON line per event: state changes, pickups, snacks, callouts, block starts/stops, the Mac's front app, a day summary at midnight, and a `sample` line every 30 seconds with the latest detector numbers (person / phone / food confidence, face turn and tilt). **Never frames or images.** It's gitignored. `DAYANPI_DATA_DIR` in `/etc/dayanpi.env` moves the whole data folder somewhere else.

Check it's filling up:

```bash
cd ~/Desktop/site-page/dayanpi
.venv/bin/python scripts/focus_stats.py            # today
.venv/bin/python scripts/focus_stats.py --days 7   # the week, plus focus by hour of day
tail -3 data/focus_log/$(date +%F).jsonl   # the raw lines
```

If you moved the data folder with `DAYANPI_DATA_DIR` in `/etc/dayanpi.env`, your shell doesn't see that file, so point the script at it: `scripts/focus_stats.py --log-dir /your/folder/focus_log`.

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

- Face the camera and sit like you normally do.
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
