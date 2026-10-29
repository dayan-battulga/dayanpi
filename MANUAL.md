# dayanpi — Run Manual

Live telemetry dashboard for a Raspberry Pi 5: stats, charts, SSE updates, and a camera feed.

After Stage 7 the app is password-protected and bound to **localhost only**. You reach it through Tailscale Serve (private) or Funnel (public).

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

## Focus tracker

The webcam sits at your desk, pointed down at your face, hands and desk. The site works out whether you're **focused**, **on your phone**, or **away**, keeps today's totals, and logs every change. It's being built one step at a time; steps 1 to 4 are in.

It runs two small models on the Pi itself (nothing goes to the cloud), and they're in `models/`. They run through OpenCV, which is already installed, so there's nothing new to `pip install`.

From across the desk a phone is only a few dozen pixels, which is too small for the model to spot reliably. So each check runs the model twice: once on the whole frame to find you, then again on a zoomed-in crop around you to find the phone. That roughly doubles the time per check, which is still fine at one check a second.

### Step 1: detector check

This shows what the camera can actually pick up at your desk. The site owns the camera, so stop it while the check runs:

```bash
cd ~/Desktop/site-page/dayanpi
git pull origin main
sudo systemctl stop dayanpi
.venv/bin/python focus_check.py
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

### Getting the files to your Mac

These are photos of you and your room, so keep them out of git (`focus_check/` is in `.gitignore`, so a normal `git add .` skips them). Copy them over SSH instead. On the Mac:

```bash
scp -r dayoon@dayoon.tail279594.ts.net:~/Desktop/site-page/dayanpi/focus_check ~/Desktop/
```

(Use whatever address you normally SSH to if that one doesn't work.) Then attach `summary.txt`, the snapshots and the `frames/` files in the chat with Claude.

If it says **No camera frames**, the service is still running. Run `sudo systemctl stop dayanpi` and try again.

### Where the models come from

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

### Steps 2 to 4: the tracker runs inside the site

Once the models are in `models/`, the site runs the detector by itself, about once a second, on the same camera frames the video feed uses. There's nothing to start. If the model files are missing it just logs a warning and the Focus card says "models not loaded on the Pi".

**The states**

| State | Means | Rule |
| --- | --- | --- |
| **focused** | At the desk, no phone in sight | You're seen in 2 checks in a row |
| **on phone** | Phone in hand | Phone spotted in 3 of the last 5 checks. Back to focused after 5 checks without it |
| **away** | Nobody at the desk | 10 seconds without you |
| **unknown** | Just started, or no camera frames for 30 s | |

The numbers come from the real frames (a quick glance at the phone doesn't count; walking out of frame for a second doesn't count either). They're constants at the top of `focus.py` if they need tuning.

**What it counts for the day:** focus time, phone time, away time, pickups (every switch into "on phone"), snacks (food spotted in 3 of 5 checks; one snack per sitting), and your best focus streak. The day rolls over at local midnight. A restart doesn't lose the day: the service rebuilds today's totals from the log when it starts (it can lose up to 30 s).

**The Focus card** on the dashboard shows the state, a live timer, today's totals, a 24-hour timeline (teal = focused, red = phone, grey = away) and a **Start block** button. A work block is just a flag for now: while it's on, a break longer than 15 minutes gets flagged as "break over". Gestures will flip it later.

**Callouts** are the things it says (out loud once the speaker's in; always logged):

- *instant pickup*: on the phone within 60 s of sitting back down
- *late night phone*: on the phone between 1 and 5 am
- *long break*: you come back after 15+ minutes away
- *break over*: 15 minutes away during a work block
- *day done*: you leave after 10 pm (once a day, with the day's totals)

**The log** lives in `data/focus_log/`, one file per day (`2026-10-29.jsonl`), one JSON line per event: state changes, pickups, snacks, callouts, block starts/stops, the Mac's front app, a day summary at midnight, and a `sample` line every 30 seconds with the latest detector numbers (person / phone / food confidence, face turn and tilt). **Never frames or images.** It's gitignored. `DAYANPI_DATA_DIR` in `/etc/dayanpi.env` moves the whole data folder somewhere else.

Check it's filling up:

```bash
cd ~/Desktop/site-page/dayanpi
.venv/bin/python focus_stats.py            # today
.venv/bin/python focus_stats.py --days 7   # the week, plus focus by hour of day
tail -3 data/focus_log/$(date +%F).jsonl   # the raw lines
```

**Routes** (all behind the login):

| Route | What |
| --- | --- |
| `GET /api/focus` | Current state, today's totals, the block, the last check's numbers, and today's timeline segments |
| `POST /api/focus/block` | `{"action": "start" \| "stop" \| "toggle"}` |
| `POST /api/mac/app` | `{"app": "Code"}`, sent by the Mac helper when the front app changes |

The focus status also rides along in every `/api/stream` update and in `/api/stats`, so the dashboard doesn't poll.

**The Mac helper** (`mac_helper/`) tells the Pi which app is in front on the Mac, so "focused" can later be split into coding / docs / browser / Slack. App names only, nothing else. Setup is in `mac_helper/README.md`: put the password in the Keychain, try `--once` and `--dry-run`, then install the LaunchAgent so it runs in the background. The Focus card shows the current app under the block button.

**Deploy it:**

```bash
cd ~/Desktop/site-page/dayanpi
git pull origin main
sudo systemctl restart dayanpi
journalctl -u dayanpi -n 20 --no-pager     # look for "focus tracker running"
```

Then open the site: the Focus card should flip to **focused** within a couple of seconds of you sitting down.

### Gestures

You can boss the LED sign around from your chair: hold an arm up in front of the camera to flip pages, or hold both up to start or stop a work block. This uses a third model, YOLO11 nano **pose**. Instead of boxes, it finds 17 points on your body (nose, eyes, ears, shoulders, elbows, wrists, hips, knees, ankles). Gestures only look at your shoulders and wrists. The code is in `pose.py` (runs the model) and `gestures.py` (turns arm positions into gestures).

#### Getting the pose model

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

#### The gestures

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

#### Tips

- Face the camera and sit like you normally do.
- Keep both shoulders in the shot. No shoulders, no gestures.
- Keep the raised hand in the shot too. The camera looks down at your desk, so a hand straight up can go off the top of the picture. Head height works better.
- Hold still. The tracker only checks 1-3 times a second, so quick waves and swipes won't register.

#### Tuning

All of these are at the top of `gestures.py`. Change them on the Mac, push, pull on the Pi, and restart the service.

| Knob | Default | What it does |
| --- | --- | --- |
| `HOLD_SECONDS` | 1 s for pages, 2 s for blocks | How long you hold before it fires |
| `RAISE_MARGIN` | `0.3` | How far above your shoulder the wrist has to be, in shoulder widths. Raise it if gestures fire by accident; lower it if they're hard to trigger. |
| `MIN_KEYPOINT_CONFIDENCE` | `0.5` | How sure the model has to be about a shoulder or wrist before it counts |
| `MIN_PERSON_CONFIDENCE` | `0.5` | How sure it has to be that there's a person there at all |
| `ALLOWED_MISSES` | `1` | How many bad checks in a row a hold survives |

---

## Pi camera (Camera Module 3 Wide)

The app can use the ribbon-cable Pi camera or the USB webcam. By default (`DAYANPI_CAMERA=auto`) it uses the Pi camera whenever it finds one and falls back to the webcam otherwise. Nothing else changes: same 640x480 picture, same `/video` stream, same detector.

### 1. Plug it in

**Power off first.** The camera connector isn't safe to plug into while the Pi is on.

```bash
sudo poweroff
```

Wait for the green light to stop blinking, then unplug the power.

- **Cable.** The camera comes with a cable for older Pis (same width at both ends). The Pi 5's camera connectors are smaller, so you need the Pi 5 camera cable: a narrow 22-pin end for the Pi and a wide 15-pin end for the camera.
- **Camera end.** Gently lift the little latch on the camera board, slide the old cable out, and push the wide end of the Pi 5 cable in the same way round the old one was (look before you pull it out). Press the latch back down.
- **Pi end.** The Pi 5 has two small connectors labeled `CAM/DISP 0` and `CAM/DISP 1`. Either one works, and the app doesn't care which. Lift the latch, slide the narrow end in straight and all the way, **with the metal contacts facing the Ethernet port**, then press the latch down.
- You can leave the webcam plugged in. That makes it easy to compare the two later.

Plug the power back in. You don't need to change `config.txt`, because official cameras get detected on their own.

### 2. Check the Pi sees it

The app grabs the camera as soon as it starts, so stop it while you check:

```bash
sudo systemctl stop dayanpi
rpicam-hello --list-cameras
```

You want a line like `0 : imx708_wide [4608x2592 10-bit RGGB] (...)`. If it says no cameras are available, it's almost always the cable: power off, reseat both ends (contacts toward the Ethernet port on the Pi end), and try again.

To see it actually run for 3 seconds (no window, nothing saved):

```bash
rpicam-hello -n -t 3000
```

### 3. Check Python can use it

The app talks to the camera through `picamera2`. Like `gpiozero`, it comes from apt, not pip.

```bash
cd ~/Desktop/site-page/dayanpi
.venv/bin/python -c "from picamera2 import Picamera2; print(Picamera2.global_camera_info())"
```

You want a list with `'Model': 'imx708_wide'` in it. Your webcam might show up in that list too, since libcamera can see webcams as well. Its `Id` has `/usb` in it, and the app skips it.

- **`No module named 'picamera2'`:** install it with `sudo apt install -y python3-picamera2` (on Raspberry Pi OS Lite, add `--no-install-recommends`). If it's installed and still missing, the venv can't see apt packages. See "Already have a venv? Switch it over" near the top of this manual.
- **An error that mentions numpy** (like `numpy.dtype size changed` or `compiled using NumPy 1.x`): the numpy pip put in the venv (it comes with opencv) doesn't match the one apt built picamera2's pieces against. Don't pip install your way out of it. Send Claude the error plus what these print:

  ```bash
  .venv/bin/python -c "import numpy; print(numpy.__version__, numpy.__file__)"
  /usr/bin/python3 -c "import numpy; print(numpy.__version__)"
  grep VERSION_CODENAME /etc/os-release
  ```

  Until that's fixed, `auto` just keeps using the webcam.

### 4. Pick the camera (or leave it on auto)

`auto` is the default, so you don't have to add anything. To force one, add lines to `/etc/dayanpi.env` with `sudo nano /etc/dayanpi.env`.

Always use the Pi camera:

```
DAYANPI_CAMERA=picamera
```

Always use the webcam:

```
DAYANPI_CAMERA=usb
DAYANPI_USB_DEVICE=/dev/v4l/by-id/usb-YOUR_WEBCAM-video-index0
```

Put any comments on their own line. systemd doesn't strip a `#` comment from the end of a value, and the app would see `picamera # blah`, warn that it's not a valid choice, and fall back to auto.

**The `/dev/video0` trap.** With the Pi camera plugged in, the Pi 5 hands some of the `/dev/video*` numbers to the camera's own hardware, so the webcam might not be `/dev/video0` anymore. Whenever you want the webcam while the Pi camera is still connected, point the app at it by name:

```bash
ls /dev/v4l/by-id/
```

Pick the one ending in `-video-index0` and put `/dev/v4l/by-id/` plus that name in `DAYANPI_USB_DEVICE`. That name stays the same however things get numbered at boot.

### 5. Make sure it picks the right one, then start the app

The app is still stopped from step 2. This prints which camera `auto` picks and why, without opening the camera:

```bash
.venv/bin/python -c "import logging, camera; logging.basicConfig(level=logging.INFO); camera.create_stream()"
```

You want something like `camera: Pi camera through picamera2 (auto, found imx708_wide)`. This uses your shell's settings, not `/etc/dayanpi.env`, so it shows what `auto` does.

Then start the app again:

```bash
sudo systemctl start dayanpi
```

Open the site. The camera card should show the new, wider view. If it doesn't, run `journalctl -u dayanpi -n 50 --no-pager` and look for camera warnings.

### 6. Compare it to the webcam with focus_check.py

Run the same desk check on both cameras and compare the two summary tables. The script doesn't read `/etc/dayanpi.env`, so put the setting in front of the command:

```bash
cd ~/Desktop/site-page/dayanpi
sudo systemctl stop dayanpi
DAYANPI_CAMERA=usb DAYANPI_USB_DEVICE=/dev/v4l/by-id/usb-YOUR_WEBCAM-video-index0 .venv/bin/python focus_check.py
cp focus_check/summary.txt focus_check/summary_usb.txt
DAYANPI_CAMERA=picamera .venv/bin/python focus_check.py
sudo systemctl start dayanpi
```

Each run clears out `focus_check/frames/`, so if you want to keep the webcam's frames, copy them to your Mac before the second run (see "Getting the files to your Mac"). Then send Claude both summaries (`summary_usb.txt` and `summary.txt`) plus the snapshots.

### What's different about the Pi camera

- **Wider view.** The Wide sees about 102° across and 67° top to bottom. The app reads the whole sensor and trims the sides to make the 4:3 picture, which comes out to roughly 85° across. Left to its default, Picamera2 would only read the middle of the sensor at this size (roughly 63° by 48°).
- **Autofocus** runs the whole time, so it stays sharp whether you lean in or sit back. It can focus as close as about 5 cm.
- **15 frames a second.** The webcam hands over ready-made JPEGs, but the Pi camera's frames get turned into JPEGs on the Pi, so it runs a bit slower to leave CPU for the detector.
- **Picture upside down?** That's a small change in `camera.py` (flip it in the camera setup). Ask Claude.

### Tuning

These live at the top of `camera.py`. Change them on the Mac, push, pull on the Pi, and restart the service.

| Knob | Default | What it does |
| --- | --- | --- |
| `PICAMERA_FPS` | `15` | Frames per second from the Pi camera. Higher is smoother but costs more CPU. |
| `PICAMERA_JPEG_QUALITY` | `80` | JPEG quality, from 0 to 100. Higher means sharper but bigger frames. |
| `PICAMERA_FULL_VIEW` | `True` | `True` is the whole wide view. `False` lets Picamera2 use its faster mode, which crops the middle, so it looks zoomed in and you're bigger in the frame. Worth a try if the phone check gets worse with the wide view. |

### When something's off

| What you see | What to do |
| --- | --- |
| `rpicam-hello` says no cameras are available | Cable: power off, reseat both ends, contacts toward the Ethernet port on the Pi end |
| `rpicam-hello` says the camera is busy or in use | The app has it: `sudo systemctl stop dayanpi` first |
| Site still shows the webcam | Run the check in step 5. Is `DAYANPI_CAMERA=usb` in `/etc/dayanpi.env`? |
| Webcam stopped working after adding the Pi camera | `/dev/video0` moved. Set `DAYANPI_USB_DEVICE` (step 4) |
| Camera card keeps saying reconnecting | Something else has the camera (an `rpicam-hello` or `focus_check.py` still running?). `journalctl -u dayanpi -n 50 --no-pager` shows why |

---

## LED sign

Two 64x32 LED panels side by side make one 128x32 sign on the wall (about 12.6" x 3.1"). It shows what the focus tracker sees, in a way you can read from across the room.

The code is in two files:

- `sign.py` draws the pages and sends them to the panels.
- `sign_glyphs.py` has the font and the icons, drawn as ASCII art you can edit by eye.

### What it shows

| Page | What's on it |
| --- | --- |
| **Now** | A big icon for what you're doing, a label, how long you've been doing it, and today's phone pickups (little phone + number) in the top right. Fire + `FOCUSED` in amber, phone + `PHONE` in red, zzz + `AWAY` in dim blue, `?` in gray when it's not sure. |
| **Today** | `FOCUS 3h12` and `PHONE 45m` in big numbers, with snacks (donut) and pickups (little phone) on the right. |
| **Callout** | An icon on the left and a message sliding past it, like "Snack time!" next to a donut, or a hand when it catches a gesture. |
| **Day done** | A big green check, `DAY DONE`, today's focus and phone time, your longest focus streak (`BEST`), and pickups. |

Times are short so they fit: `45s`, `12m`, `1h05`, `10h30`.

The icons are `fire`, `phone`, `zzz`, `question`, `food` (a donut), `cup`, `check`, `moon`, `hand` and `alert`. A callout with any other icon name shows the question mark.

Nothing ever goes above 200 out of 255 on any color, even at full brightness. Full white is blinding up close, and both panels on full white would pull about 8 A from a 4 A supply. Every page also takes a brightness from 0 to 1, for dimming at night.

### Changing the font or an icon

Open `sign_glyphs.py`. Each letter is 7 lines of 5 characters (`#` on, `.` off). Each icon is 16 lines of 16 characters, where each letter is a color from `PALETTE` and `.` is off. Edit, then run the tests. They catch a line that's the wrong length or a color letter that isn't in the palette:

```bash
python -m pytest tests/test_sign.py -q
```

To see a page without the panels, render it to a PNG that looks like the real thing. Run this on your Mac from the repo folder:

```bash
python3 -c "import sign; open('/tmp/sign.png', 'wb').write(sign.render_preview_png(sign.render_page(sign.NowPage('working', 3900, 3))))"
open /tmp/sign.png
```

### Bringing up the panels

#### Heads up: the sign and the rover share pins

The bonnet uses 14 GPIO pins, and six of them are the rover's motor pins (12, 13, 17, 22, 23, 27). So the rover stays unplugged while the sign is on. Also, right now `app.py` sets up the motors at startup and holds those pins the whole time the service runs. The sign can't run alongside that, so the smoke test below stops the service first.

#### What you need

- 2 HUB75 RGB panels, 64x32, with the ribbon cables and power cables they come with
- Adafruit RGB Matrix Bonnet
- A 5V 4A power supply with a barrel plug, for the panels
- The Pi's normal USB-C supply. Use a strong one (the official 27W); a weak one causes errors here (see the table at the end).

#### Wiring

Do all of this with everything unplugged.

1. Push the bonnet onto the Pi's 40-pin header. Line it up with every pin and push it all the way down.
2. Run a ribbon cable from the bonnet to the first panel's **IN** connector. On the back of each panel, the arrows point away from IN and toward OUT.
3. Run the second ribbon cable from the first panel's **OUT** to the second panel's **IN**.
4. Panel power: each panel's power cable has a red and a black lead. Both red leads go into the bonnet's **+** screw terminal, and both black leads go into **−**. Tighten the screws and give each wire a tug.
5. Plug the 5V 4A supply's barrel plug into the bonnet's barrel jack, but don't plug the supply into the wall yet.

One 4A supply for both panels is fine here. Adafruit runs two panels off one 4A adapter, and this sign is mostly dark and capped at 200.

#### Power-up order

Plug in the Pi's USB-C first, then plug in the panel supply. To turn it off, run `sudo poweroff`, wait for the green light to stop blinking, then unplug both.

#### One-time setup on the Pi

Update first. The PIO driver the panels need is part of the kernel:

```bash
sudo apt update
sudo apt upgrade -y
```

Let the `gpio` group use the PIO. Open the udev rules file:

```bash
sudo nano /etc/udev/rules.d/99-com.rules
```

Add this line near the top:

```text
SUBSYSTEM=="*-pio", GROUP="gpio", MODE="0660"
```

Save with `Ctrl+S`, exit with `Ctrl+X`, then reboot:

```bash
sudo reboot
```

After the reboot, check it worked:

```bash
ls -l /dev/pio*   # the group should say gpio
groups            # should include gpio (it already does from the rover)
```

Install Adafruit's Piomatter library into the dashboard's venv:

```bash
cd ~/Desktop/site-page/dayanpi
.venv/bin/pip install Adafruit-Blinka-Raspberry-Pi5-Piomatter
.venv/bin/python -c "import adafruit_blinka_raspberry_pi5_piomatter"   # no output = good
```

It's not in `requirements.txt` on purpose. It only works on a Pi 5, and `sign.py` only imports it once you actually turn on the panels, so the app and the tests still run on the Mac. If pip ends up building it from source and complains about a missing compiler, run `sudo apt install -y build-essential python3-dev` and try again.

#### Smoke test

This shows each page for 4 seconds, then scrolls a message past the hand icon. The service holds the sign's pins (see the heads up above), so stop it first:

```bash
cd ~/Desktop/site-page/dayanpi
git pull origin main
sudo systemctl stop dayanpi
.venv/bin/python - <<'EOF'
import time

import sign

panel = sign.PanelOutput()
pages = [
    sign.NowPage("working", 3900, 3),
    sign.NowPage("phone", 45, 14),
    sign.NowPage("away", 725, 14),
    sign.TodayPage(3 * 3600 + 12 * 60, 45 * 60, 14, 2),
    sign.SummaryPage(6 * 3600 + 40 * 60, 52 * 60, 14, 80 * 60),
]
for page in pages:
    panel.show(sign.render_page(page))
    time.sleep(4)
message = "Hello from the sign!"
for scroll_px in range(sign.callout_width(message) + 1):
    panel.show(sign.render_page(sign.CalloutPage(message, "hand", (200, 140, 90), scroll_px)))
    time.sleep(0.03)
EOF
sudo systemctl start dayanpi
```

The first page should be a fire icon on the far left, then `FOCUSED` over a big `1h05`, and a little phone with `3` in the top right corner. The panels go dark when the script ends.

#### If something's off

| What you see | What to do |
| --- | --- |
| `Failed to open PIO device` | Adafruit says this is almost always the Pi's power supply, so try the official 27W one. Also check `ls -l /dev/pio*` shows `gpio` and that you rebooted after adding the udev rule. Adafruit's guide also mentions `sudo rpi-update` for older Pi 5 boards. That installs pre-release firmware, so only try it if nothing else works. |
| `No module named 'adafruit_blinka_raspberry_pi5_piomatter'` | The install went into the wrong Python. Use `.venv/bin/pip`, not plain `pip`. |
| The two halves are swapped (time on the left, icon on the right) | Swap the two panels' spots on the wall. |
| Upside down | Set `PANEL_ORIENTATION = "R180"` in `sign.py`. |
| Red and blue are swapped | Set `PANEL_PINOUT = "AdafruitMatrixBonnetBGR"` in `sign.py`. |
| Garbage, flicker, or one panel copies the other | Check the ribbons go bonnet → IN, OUT → IN (follow the arrows) and are pushed all the way in. Make sure nothing else is using the pins (stop the `dayanpi` service). |
| Panels flicker or the Pi reboots on bright pages | The supply is too weak or a screw terminal is loose. |

### How the app drives it

The app renders the sign a few times a second whatever you've set, so the dashboard always shows the preview under the Focus card. `DAYANPI_SIGN` in `/etc/dayanpi.env` picks what else happens:

| Value | What |
| --- | --- |
| `preview` (default) | Website preview only |
| `panel` | Website preview **and** the real panels through the Matrix Bonnet |
| `off` | Nothing, not even the preview |

What it shows is decided in `sign_controller.py`: the **Now** page by default, **Today** and **Day done** as you flip pages (gestures, or `/api/focus/block` for now), callouts scrolling across whatever page is up, the **Day done** page by itself for 15 minutes after the day-done callout, and a dimmer "ambient" sign during a work block and at night (11 pm to 7 am). `GET /api/sign.png` is the preview image on its own.

**The motors and the sign can't both be on.** The Matrix Bonnet uses GPIO 4, 5, 6, 12, 13, 16, 17, 20, 21, 22, 23, 24, 26 and 27, which includes all six motor pins. With `DAYANPI_SIGN=panel` the app doesn't touch the motor pins at all (the Drive card is hidden anyway while the rover's paused, and `/api/drive` answers 503).


---

## Voice (USB speaker)

The focus tracker can say things out loud, like "Phone down." or "Break's over.", through a plain USB speaker. The voice is **off** until you turn it on. While it's off, the app just writes what it would have said to the log (`voice off, would say: 'Phone down.'`).

One thing to know first: the dashboard runs as a systemd **system** service, so it can't use the desktop's sound system (PipeWire). It plays straight to the speaker with `aplay` instead. That's why you tell it exactly which device the speaker is.

### 1. Plug in the speaker and find its name

Plug it into any USB port, then on the Pi:

```bash
aplay -l
```

Look for the USB one. It'll be something like this (your names will be different):

```text
card 2: Device [USB Audio Device], device 0: USB Audio [USB Audio]
```

The word right after `card 2:` is the card's name (`Device` here), so the speaker's ALSA name is `plughw:CARD=Device,DEV=0`. To see the exact names ALSA knows about:

```bash
aplay -L | grep plughw
```

Use that `plughw:CARD=...` form everywhere below:

- **`plughw`, not `hw`.** `plughw` converts the voice's audio into whatever the speaker accepts. Plain `hw` often just refuses.
- **`CARD=Device`, not a number like `plughw:2,0`.** Card numbers can change after a reboot or when you plug in other USB stuff. The name doesn't.

### 2. Make sure it plays

```bash
speaker-test -D plughw:CARD=Device,DEV=0 -c 2 -t wav -l 1
```

You should hear "Front left, front right" once. (Leave off `-l 1` and it loops until you press Ctrl+C.) Silent? Check the volume (below) first.

### 3. Let the service use it

The service runs as `dayoon`, and only the `audio` group can open sound devices:

```bash
groups dayoon   # should include "audio"
```

If it's missing:

```bash
sudo usermod -aG audio dayoon
```

The service picks that up the next time it restarts. Your own SSH session only sees it after you log out and back in.

### 4. Quick start: espeak-ng

espeak-ng sounds pretty robotic, but it's tiny and instant. Install it and try it out:

```bash
sudo apt install espeak-ng
echo "Phone down." | espeak-ng --stdout -v en-us -s 165 --stdin | aplay -q -D plughw:CARD=Device,DEV=0
```

That's exactly what the dashboard runs for each phrase. To test it the way the service will run it (as a system service, with no desktop session), try:

```bash
sudo systemd-run --uid=dayoon --wait --pipe /bin/sh -c 'echo "Testing from a system service." | espeak-ng --stdout -v en-us -s 165 --stdin | aplay -q -D plughw:CARD=Device,DEV=0'
```

If you hear that, the dashboard will work too. Now turn it on. Open the env file:

```bash
sudo nano /etc/dayanpi.env
```

Add these two lines (with your speaker's name):

```
DAYANPI_VOICE=espeak
DAYANPI_AUDIO_DEVICE=plughw:CARD=Device,DEV=0
```

Restart and check the log:

```bash
sudo systemctl restart dayanpi
journalctl -u dayanpi -n 30 --no-pager | grep -i voice
```

You want `voice on: espeak through aplay on plughw:CARD=Device,DEV=0`. If the voice can't run (say espeak-ng isn't installed), the log says why once and the voice stays off. The rest of the site keeps working either way.

### 5. Nicer voice: Piper

Piper sounds a lot more human. It's a pip package, and it goes into the dashboard's venv:

```bash
cd ~/Desktop/site-page/dayanpi
.venv/bin/pip install piper-tts
```

It's not in `requirements.txt` on purpose. Piper plus ONNX Runtime is about 50 MB that only the voice needs. And don't `sudo apt install piper`: that's an unrelated app for gaming mice.

Next, grab a voice. Each voice is two files, an `.onnx` and an `.onnx.json`, and Piper needs both. This downloads `en_US-lessac-medium` (about 60 MB) from the official voice collection (`rhasspy/piper-voices` on Hugging Face) into `~/piper-voices`:

```bash
mkdir -p ~/piper-voices
cd ~/piper-voices
~/Desktop/site-page/dayanpi/.venv/bin/python -m piper.download_voices en_US-lessac-medium
ls   # en_US-lessac-medium.onnx  en_US-lessac-medium.onnx.json
```

Or the same two files with wget:

```bash
cd ~/piper-voices
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
```

Try it:

```bash
echo "Break's over." | ~/Desktop/site-page/dayanpi/.venv/bin/python -m piper --model ~/piper-voices/en_US-lessac-medium.onnx --output-raw | aplay -q -D plughw:CARD=Device,DEV=0 -r 22050 -f S16_LE -t raw -
```

`22050` is the voice's sample rate. It lives in the `.onnx.json` under `audio` → `sample_rate`, and the dashboard reads it from there on its own. (A different voice might use another rate. If it sounds like a chipmunk or slow-mo here, that's why.)

Then point the dashboard at it in `/etc/dayanpi.env`, using the full path:

```
DAYANPI_VOICE=piper
DAYANPI_PIPER_MODEL=/home/dayoon/piper-voices/en_US-lessac-medium.onnx
DAYANPI_AUDIO_DEVICE=plughw:CARD=Device,DEV=0
```

```bash
sudo systemctl restart dayanpi
journalctl -u dayanpi -n 30 --no-pager | grep -i voice
```

Piper loads the voice fresh for every phrase, so expect a short pause before it talks.

### Volume

The speaker has no volume knob, so you set it in software:

```bash
alsamixer
```

Press **F6** and pick the USB speaker, then use the up/down arrows. **Esc** quits. If the level resets after a reboot, save it once you like it:

```bash
sudo alsactl store
```

### Good to know

- Phrases play one at a time. If 3 are already waiting, new ones get dropped. They're about what you're doing right now, so a late one would just be confusing.
- Unplugging the speaker doesn't break anything. Phrases fail (and the log says so) until it's back, no restart needed.
- To turn it off, set `DAYANPI_VOICE=off` in `/etc/dayanpi.env` (or delete the line) and restart. Off is the default.

### When it doesn't talk

Check the log first: `journalctl -u dayanpi -n 50 --no-pager | grep -i voice`

| Log says | What to do |
| --- | --- |
| `espeak-ng isn't installed` | `sudo apt install espeak-ng`, then restart |
| `piper-tts isn't installed in the dashboard's venv` | `.venv/bin/pip install piper-tts` in the dashboard folder, then restart |
| `there's no Piper voice at ...` or `... .onnx.json is missing` | `DAYANPI_PIPER_MODEL` needs the full path, and both files need to be in that folder |
| `Device or resource busy` | Something else has the speaker, usually the desktop's audio. `sudo fuser -v /dev/snd/*` shows who. Close that, or wait a few seconds and it'll let go |
| `Permission denied` | `dayoon` isn't in the `audio` group (step 3) |
| Some other `audio open error` (like `No such device`) | Speaker unplugged, or the name's off (re-check `aplay -L \| grep plughw`). It can also mean `dayoon` isn't in the `audio` group: without it, ALSA can't even look the card up by name |
| Nothing at all | Is `DAYANPI_VOICE` set, and did you restart? Without `DAYANPI_AUDIO_DEVICE`, aplay uses ALSA's default device, which usually isn't the USB speaker. Also check the volume |

---

## Driving the rover

**Paused right now.** The motors are unplugged and the Drive card is hidden. To bring it back, plug the motor wires back in (the pin table is in `CLAUDE.md`), remove `hidden` from the `drive-card` div in `static/index.html`, and add `<script type="module" src="/drive.js"></script>` back after the `app.js` line.

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
| Power card is red | The battery or supply is too weak, especially with the motors running. Undervoltage can reboot the Pi mid-drive |

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
