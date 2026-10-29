# Pi camera (Camera Module 3 Wide)

Part of the dayanpi docs. Setting up and running the Pi is in the [manual](MANUAL.md).

The app can use the ribbon-cable Pi camera or the USB webcam. By default (`DAYANPI_CAMERA=auto`) it uses the Pi camera whenever it finds one and falls back to the webcam otherwise. Nothing else changes: same 640x480 picture, same `/video` stream, same detector.

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

## 4. Pick the camera (or leave it on auto)

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
DAYANPI_CAMERA=usb DAYANPI_USB_DEVICE=/dev/v4l/by-id/usb-YOUR_WEBCAM-video-index0 .venv/bin/python scripts/focus_check.py
cp focus_check/summary.txt focus_check/summary_usb.txt
DAYANPI_CAMERA=picamera .venv/bin/python scripts/focus_check.py
sudo systemctl start dayanpi
```

Each run clears out `focus_check/frames/`, so if you want to keep the webcam's frames, copy them to your Mac before the second run (see [Getting the files to your Mac](focus-tracker.md#getting-the-files-to-your-mac)). Then send Claude both summaries (`summary_usb.txt` and `summary.txt`) plus the snapshots.

## What's different about the Pi camera

- **Wider view.** The Wide sees about 102° across and 67° top to bottom. The app reads the whole sensor and trims the sides to make the 4:3 picture, which comes out to roughly 85° across. Left to its default, Picamera2 would only read the middle of the sensor at this size (roughly 63° by 48°).
- **Autofocus** runs the whole time, so it stays sharp whether you lean in or sit back. It can focus as close as about 5 cm.
- **15 frames a second.** The webcam hands over ready-made JPEGs, but the Pi camera's frames get turned into JPEGs on the Pi, so it runs a bit slower to leave CPU for the detector.
- **Picture upside down?** That's a small change in `dayanpi/hardware/camera.py` (flip it in the camera setup). Ask Claude.

## Tuning

These live at the top of `dayanpi/hardware/camera.py`. Change them on the Mac, push, pull on the Pi, and restart the service.

| Knob | Default | What it does |
| --- | --- | --- |
| `PICAMERA_FPS` | `15` | Frames per second from the Pi camera. Higher is smoother but costs more CPU. |
| `PICAMERA_JPEG_QUALITY` | `80` | JPEG quality, from 0 to 100. Higher means sharper but bigger frames. |
| `PICAMERA_FULL_VIEW` | `True` | `True` is the whole wide view. `False` lets Picamera2 use its faster mode, which crops the middle, so it looks zoomed in and you're bigger in the frame. Worth a try if the phone check gets worse with the wide view. |

## When something's off

| What you see | What to do |
| --- | --- |
| `rpicam-hello` says no cameras are available | Cable: power off, reseat both ends, contacts toward the Ethernet port on the Pi end |
| `rpicam-hello` says the camera is busy or in use | The app has it: `sudo systemctl stop dayanpi` first |
| Site still shows the webcam | Run the check in step 5. Is `DAYANPI_CAMERA=usb` in `/etc/dayanpi.env`? |
| Webcam stopped working after adding the Pi camera | `/dev/video0` moved. Set `DAYANPI_USB_DEVICE` (step 4) |
| Camera card keeps saying reconnecting | Something else has the camera (an `rpicam-hello` or `scripts/focus_check.py` still running?). `journalctl -u dayanpi -n 50 --no-pager` shows why |
