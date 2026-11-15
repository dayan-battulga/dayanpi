# Pi camera (Camera Module 3 Wide)

Part of the dayanpi docs. Setting up and running the Pi is in the [manual](MANUAL.md).

The app can use the ribbon-cable Pi camera, the USB webcam, or [both at once](#using-both-cameras). By default (`DAYANPI_CAMERA=auto`) it uses the Pi camera whenever it finds one and falls back to the webcam otherwise. Nothing else changes: same `/video` stream, same detector. The only difference is the picture's shape: the webcam gives 640x480 (4:3) and the Pi camera 768x432 (16:9), so you get the Wide lens's whole width.

## 1. Plug it in

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

## 2. Check the Pi sees it

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

## 3. Check Python can use it

The app talks to the camera through `picamera2`, which comes from apt, not pip.

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

## 4. Pick the camera (or leave it on auto)

`auto` is the default, so you don't have to add anything. To force one, add lines to `/etc/dayanpi.env` with `sudo nano /etc/dayanpi.env`.

Always use the Pi camera:

```
DAYANPI_CAMERA=picamera
```

Always use the webcam:

```
DAYANPI_CAMERA=usb
```

Put any comments on their own line. systemd doesn't strip a `#` comment from the end of a value, and the app would see `picamera # blah`, warn that it's not a valid choice, and fall back to auto.

**The `/dev/video0` trap.** With the Pi camera plugged in, the Pi 5 hands some of the `/dev/video*` numbers to the camera's own hardware, so the webcam might not be `/dev/video0` anymore. The app handles this for you: it looks for the webcam's stable name in `/dev/v4l/by-id/` first, and only tries `/dev/video0` if there isn't one. That name stays the same however things get numbered at boot.

You only need to step in if you have two webcams and it picks the wrong one. See what's there:

```bash
ls /dev/v4l/by-id/
```

Pick the one ending in `-video-index0` and put `/dev/v4l/by-id/` plus that name in `/etc/dayanpi.env`:

```
DAYANPI_USB_DEVICE=/dev/v4l/by-id/usb-YOUR_WEBCAM-video-index0
```

## 5. Make sure it picks the right one, then start the app

The app is still stopped from step 2. This prints which camera `auto` picks and why, without opening the camera:

```bash
.venv/bin/python -c "import logging; from dayanpi.hardware import camera; logging.basicConfig(level=logging.INFO); camera.create_stream()"
```

You want something like `camera: Pi camera through picamera2 (auto, found imx708_wide)`. This uses your shell's settings, not `/etc/dayanpi.env`, so it shows what `auto` does.

Then start the app again:

```bash
sudo systemctl start dayanpi
```

Open the site. The camera card should show the new, wider view. If it doesn't, run `journalctl -u dayanpi -n 50 --no-pager` and look for camera warnings.

## 6. Compare it to the webcam with the detector check

Run the same desk check on both cameras and compare the two summary tables. The script doesn't read `/etc/dayanpi.env`, so put the setting in front of the command:

```bash
cd ~/Desktop/site-page/dayanpi
sudo systemctl stop dayanpi
DAYANPI_CAMERA=usb .venv/bin/python -m dayanpi.focus.check
cp focus_check/summary.txt focus_check/summary_usb.txt
DAYANPI_CAMERA=picamera .venv/bin/python -m dayanpi.focus.check
sudo systemctl start dayanpi
```

Each run clears out `focus_check/frames/`, so if you want to keep the webcam's frames, copy them to your Mac before the second run (see [Getting the files to your Mac](focus-tracker.md#getting-the-files-to-your-mac)). Then send Claude both summaries (`summary_usb.txt` and `summary.txt`) plus the snapshots.

## Using both cameras

You can run both at once. One camera faces you straight on (the **front** camera) and the other watches from the side. By default the webcam is in front and the Pi camera is on the side.

Add this to `/etc/dayanpi.env` with `sudo nano /etc/dayanpi.env`, on its own line:

```
DAYANPI_CAMERA=both
```

Pi camera in front and the webcam on the side? Add this line too:

```
DAYANPI_FRONT_CAMERA=picamera
```

It's `usb` (webcam in front) when it isn't there. Anything other than `usb` or `picamera` logs a warning and puts the webcam in front. It only matters with `both`.

Then restart and check the app found both:

```bash
sudo systemctl restart dayanpi
journalctl -u dayanpi -n 30 --no-pager | grep -i camera
```

You want these two lines (the first one is the front camera). With the webcam in front:

```text
INFO dayanpi.hardware.camera: camera: USB webcam at /dev/v4l/by-id/usb-...-video-index0 (DAYANPI_CAMERA=both, DAYANPI_FRONT_CAMERA=usb)
INFO dayanpi.hardware.camera: side camera: Pi camera through picamera2 (DAYANPI_CAMERA=both)
```

With `DAYANPI_FRONT_CAMERA=picamera`:

```text
INFO dayanpi.hardware.camera: camera: Pi camera through picamera2 (DAYANPI_CAMERA=both, DAYANPI_FRONT_CAMERA=picamera)
INFO dayanpi.hardware.camera: side camera: USB webcam at /dev/v4l/by-id/usb-...-video-index0 (DAYANPI_CAMERA=both)
```

- **Front means front, whichever camera it is.** Faces, gestures and `/video` come from the front camera, and the `side_` numbers in the log and `/video/side` come from the side one. Swap the cameras and the setting, and everything follows.
- **The webcam finds itself.** The app takes the first name in `/dev/v4l/by-id/` ending in `-video-index0`. You only need `DAYANPI_USB_DEVICE` if you have two webcams and it picks the wrong one.
- **Arducam camera?** Official cameras get detected on their own, but an Arducam one needs a line in `config.txt`, like `dtoverlay=imx708,cam0` for the `CAM/DISP 0` connector.
- **The feeds.** `/video` is the front camera and `/video/side` is the side one. Each allows 2 viewers at a time, so a side feed left open somewhere can't lock you out of the front. With any other `DAYANPI_CAMERA` setting, `/video/side` is a 404.
- **The detector runs on both.** Every check scans a new frame from each camera, and the tracker gets one combined reading. Faces and gestures only use the front camera. [With both cameras](focus-tracker.md#with-both-cameras) in the focus tracker guide has what that means day to day and how to tell which camera caught a phone.
- **The dashboard.** The Camera card shows both feeds, labeled Front and Side, each with its own boxes. See [The dashboard](MANUAL.md#the-dashboard).
- **Webcam unplugged at startup?** The app tries `/dev/video0` until the webcam shows up. With the Pi camera connected that's the Pi camera's own hardware, so the Pi camera can fail to start in the meantime. Plug the webcam in and it should sort itself out. If it doesn't, restart the service.
- **The detector check.** `dayanpi.focus.check` doesn't read `/etc/dayanpi.env`, so put `DAYANPI_CAMERA=usb` or `DAYANPI_CAMERA=picamera` in front of it to pick which camera it checks, like in step 6.

## What's different about the Pi camera

- **Wider view.** The Wide sees about 102° across and 67° top to bottom, and the app keeps all of it: it reads the whole sensor and asks for a 768x432 picture, which is 16:9 like the sensor. A 4:3 picture like 640x480 would make the camera trim the sides, down to roughly 85° across. Left to its default, Picamera2 would only read the middle of the sensor (roughly 79° by 48°).
- **16:9 all the way through.** 768x432 is about as many pixels as 640x480, so it costs the Pi about the same. The detector shrinks it to 640x360 and pads the top and bottom to fit its 640x480 input, then maps the boxes back. The dashboard's Camera card takes the shape of each feed, so the boxes still land on the right spot. One catch: the full-frame pass sees you about 25% smaller than with the old 4:3 picture, since the same input now covers a wider view. If `person` drops a lot in the sample lines, that's why. The zoomed phone pass crops the 768x432 frame itself, so it only has about 10% less detail to work with.
- **Autofocus** runs the whole time, so it stays sharp whether you lean in or sit back. It can focus as close as about 5 cm.
- **15 frames a second.** The webcam hands over ready-made JPEGs, but the Pi camera's frames get turned into JPEGs on the Pi, so it runs a bit slower to leave CPU for the detector.
- **Picture upside down?** One line in `/etc/dayanpi.env` fixes it. See [Upside-down picture](#upside-down-picture).

## Upside-down picture

Mounted the Pi camera upside down? Add this to `/etc/dayanpi.env` with `sudo nano /etc/dayanpi.env`, on its own line:

```
DAYANPI_PICAMERA_ROTATION=180
```

Then restart and check it took:

```bash
sudo systemctl restart dayanpi
journalctl -u dayanpi -n 30 --no-pager | grep -i "turning the picture"
```

You want `Pi camera: turning the picture 180 degrees (DAYANPI_PICAMERA_ROTATION)`.

- **It's free.** The camera flips the picture itself before the app ever sees it, so the Pi's CPU doesn't do any extra work.
- **Only the Pi camera.** It works however the Pi camera's being used: `picamera`, `auto` when it picks the Pi camera, or in front or on the side with `both`. The webcam never gets flipped.
- **Only 0 or 180.** `0` is the default. The camera can only flip, not turn sideways, so there's no 90. Anything else logs a warning and leaves the picture alone.
- **The `rpicam-*` tools don't know about it.** They don't read `/etc/dayanpi.env`, so they'll still show it upside down. Give them `--rotation 180` yourself, like `rpicam-hello --rotation 180`.
- **The detector check doesn't either.** Put it in front of the command, like the camera setting: `DAYANPI_CAMERA=picamera DAYANPI_PICAMERA_ROTATION=180 .venv/bin/python -m dayanpi.focus.check`.

## Tuning

These live at the top of `dayanpi/hardware/camera.py`. Change them on the Mac, push, pull on the Pi, and restart the service.

| Knob | Default | What it does |
| --- | --- | --- |
| `PICAMERA_FPS` | `15` | Frames per second from the Pi camera. Higher is smoother but costs more CPU. |
| `PICAMERA_WIDTH`, `PICAMERA_HEIGHT` | `768`, `432` | The Pi camera's picture size. Keep it 16:9 or the camera trims the sides. Bigger costs more CPU for the JPEGs and the zoomed phone pass, but the full-frame pass always shrinks it to 640 wide anyway. The webcam stays at 640x480 (`FRAME_WIDTH`, `FRAME_HEIGHT`). |
| `PICAMERA_JPEG_QUALITY` | `80` | JPEG quality, from 0 to 100. Higher means sharper but bigger frames. |
| `PICAMERA_FULL_VIEW` | `True` | `True` is the whole wide view. `False` lets Picamera2 use its faster mode, which crops the middle, so it looks zoomed in and you're bigger in the frame. Worth a try if the phone check gets worse with the wide view. |

## When something's off

| What you see | What to do |
| --- | --- |
| `rpicam-hello` says no cameras are available | Cable: power off, reseat both ends, contacts toward the Ethernet port on the Pi end |
| `rpicam-hello` says the camera is busy or in use | The app has it: `sudo systemctl stop dayanpi` first |
| Site still shows the webcam | Run the check in step 5. Is `DAYANPI_CAMERA=usb` in `/etc/dayanpi.env`? |
| Webcam stopped working after adding the Pi camera | `ls /dev/v4l/by-id/` should list it. Nothing there? Check the USB cable. Two webcams? Set `DAYANPI_USB_DEVICE` (step 4) |
| `/video/side` gives a 404 | `DAYANPI_CAMERA=both` isn't in `/etc/dayanpi.env`, or the service hasn't restarted since you added it |
| `/video/side` never shows a picture | `journalctl -u dayanpi -n 50 --no-pager \| grep -i camera`. If it says `can't open Pi camera 0`, run the check in step 3 |
| Camera card keeps saying reconnecting | Something else has the camera (an `rpicam-hello` or the detector check still running?). `journalctl -u dayanpi -n 50 --no-pager` shows why |
