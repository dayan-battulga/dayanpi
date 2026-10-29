# LED sign

Part of the dayanpi docs. Setting up and running the Pi is in the [manual](MANUAL.md).

Two 64x32 LED panels side by side make one 128x32 sign on the wall (about 12.6" x 3.1"). It shows what the focus tracker sees, in a way you can read from across the room.

The code is in `dayanpi/sign/`:

- `renderer.py` draws the pages and sends them to the panels.
- `glyphs.py` has the font and the icons, drawn as ASCII art you can edit by eye.
- `controller.py` decides which page shows when.

## What it shows

| Page | What's on it |
| --- | --- |
| **Now** | A big icon for what you're doing, a label, how long you've been doing it, and today's phone pickups (little phone + number) in the top right. Fire + `FOCUSED` in amber, phone + `PHONE` in red, zzz + `AWAY` in dim blue, `?` in gray when it's not sure. |
| **Today** | `FOCUS 3h12` and `PHONE 45m` in big numbers, with snacks (donut) and pickups (little phone) on the right. |
| **Callout** | An icon on the left and a message sliding past it, like "Snack number 2." next to a donut, or "Sat down 30 seconds ago and already on the phone." next to a phone. |
| **Day done** | A big green check, `DAY DONE`, today's focus and phone time, your longest focus streak (`BEST`), and pickups. |

Times are short so they fit: `45s`, `12m`, `1h05`, `10h30`.

The icons are `fire`, `phone`, `zzz`, `question`, `food` (a donut), `check`, `moon` and `alert`. A callout with any other icon name shows the question mark.

Nothing ever goes above 200 out of 255 on any color, even at full brightness. Full white is blinding up close, and both panels on full white would pull about 8 A from a 4 A supply. Every page also takes a brightness from 0 to 1, for dimming at night.

## Changing the font or an icon

Open `dayanpi/sign/glyphs.py`. Each letter is 7 lines of 5 characters (`#` on, `.` off). Each icon is 16 lines of 16 characters, where each letter is a color from `PALETTE` and `.` is off. Edit, then run the tests. They catch a line that's the wrong length or a color letter that isn't in the palette:

```bash
python -m pytest tests/test_sign.py -q
```

To see a page without the panels, render it to a PNG that looks like the real thing. Run this on your Mac from the repo folder:

```bash
python3 -c "from dayanpi.sign import renderer as sign; open('/tmp/sign.png', 'wb').write(sign.render_preview_png(sign.render_page(sign.NowPage('working', 3900, 3))))"
open /tmp/sign.png
```

## Bringing up the panels

### Heads up: the sign and the rover share pins

The bonnet uses 14 GPIO pins, and six of them are the rover's motor pins (12, 13, 17, 22, 23, 27). So the rover stays unplugged while the sign is on. With `DAYANPI_SIGN=panel` the app leaves the motor pins alone; with any other setting it grabs them at startup, which is why the smoke test below stops the service first.

### What you need

- 2 HUB75 RGB panels, 64x32, with the ribbon cables and power cables they come with
- Adafruit RGB Matrix Bonnet
- A 5V 4A power supply with a barrel plug, for the panels
- The Pi's normal USB-C supply. Use a strong one (the official 27W); a weak one causes errors here (see the table at the end).

### Wiring

Do all of this with everything unplugged.

1. Push the bonnet onto the Pi's 40-pin header. Line it up with every pin and push it all the way down.
2. Run a ribbon cable from the bonnet to the first panel's **IN** connector. On the back of each panel, the arrows point away from IN and toward OUT.
3. Run the second ribbon cable from the first panel's **OUT** to the second panel's **IN**.
4. Panel power: each panel's power cable has a red and a black lead. Both red leads go into the bonnet's **+** screw terminal, and both black leads go into **−**. Tighten the screws and give each wire a tug.
5. Plug the 5V 4A supply's barrel plug into the bonnet's barrel jack, but don't plug the supply into the wall yet.

One 4A supply for both panels is fine here. Adafruit runs two panels off one 4A adapter, and this sign is mostly dark and capped at 200.

### Power-up order

Plug in the Pi's USB-C first, then plug in the panel supply. To turn it off, run `sudo poweroff`, wait for the green light to stop blinking, then unplug both.

### One-time setup on the Pi

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

It's not in `requirements.txt` on purpose. It only works on a Pi 5, and `dayanpi/sign/renderer.py` only imports it once you actually turn on the panels, so the app and the tests still run on the Mac. If pip ends up building it from source and complains about a missing compiler, run `sudo apt install -y build-essential python3-dev` and try again.

### Smoke test

This shows each page for 4 seconds, then scrolls a message past the check icon. The service holds the sign's pins (see the heads up above), so stop it first:

```bash
cd ~/Desktop/site-page/dayanpi
git pull origin main
sudo systemctl stop dayanpi
.venv/bin/python - <<'EOF'
import time

from dayanpi.sign import renderer as sign

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
for scroll_px in range(sign.measure_callout(message) + 1):
    panel.show(sign.render_page(sign.CalloutPage(message, "check", (200, 140, 90), scroll_px)))
    time.sleep(0.03)
EOF
sudo systemctl start dayanpi
```

The first page should be a fire icon on the far left, then `FOCUSED` over a big `1h05`, and a little phone with `3` in the top right corner. The panels go dark when the script ends.

### If something's off

| What you see | What to do |
| --- | --- |
| `Failed to open PIO device` | Adafruit says this is almost always the Pi's power supply, so try the official 27W one. Also check `ls -l /dev/pio*` shows `gpio` and that you rebooted after adding the udev rule. Adafruit's guide also mentions `sudo rpi-update` for older Pi 5 boards. That installs pre-release firmware, so only try it if nothing else works. |
| `No module named 'adafruit_blinka_raspberry_pi5_piomatter'` | The install went into the wrong Python. Use `.venv/bin/pip`, not plain `pip`. |
| The two halves are swapped (time on the left, icon on the right) | Swap the two panels' spots on the wall. |
| Upside down | Set `PANEL_ORIENTATION = "R180"` in `dayanpi/sign/renderer.py`. |
| Red and blue are swapped | Set `PANEL_PINOUT = "AdafruitMatrixBonnetBGR"` in `dayanpi/sign/renderer.py`. |
| Garbage, flicker, or one panel copies the other | Check the ribbons go bonnet → IN, OUT → IN (follow the arrows) and are pushed all the way in. Make sure nothing else is using the pins (stop the `dayanpi` service). |
| Panels flicker or the Pi reboots on bright pages | The supply is too weak or a screw terminal is loose. |

## How the app drives it

`DAYANPI_SIGN` in `/etc/dayanpi.env` picks where the sign goes. With `preview` (the default) or `panel`, the app renders it a few times a second and the dashboard shows the preview in the LED sign card next to the camera:

| Value | What |
| --- | --- |
| `preview` (default) | Website preview only |
| `panel` | Website preview **and** the real panels through the Matrix Bonnet |
| `off` | Nothing, not even the preview |

What it shows is decided in `dayanpi/sign/controller.py`: the **Now** page by default, **Today** and **Day done** as you flip pages with the one-hand gestures or the **Flip sign page** button on the dashboard (they fall back to **Now** after 20 s), callouts scrolling across whatever page is up, the **Day done** page by itself for 15 minutes after the day-done callout, and a dimmer "ambient" sign during a work block and at night (11 pm to 7 am). `GET /api/sign.png` is the preview image on its own.

**The motors and the sign can't both be on.** The Matrix Bonnet uses GPIO 4, 5, 6, 12, 13, 16, 17, 20, 21, 22, 23, 24, 26 and 27, which includes all six motor pins. With `DAYANPI_SIGN=panel` the app doesn't touch the motor pins at all (the Drive card is hidden anyway while the rover's paused, and `/api/drive` answers 503).
