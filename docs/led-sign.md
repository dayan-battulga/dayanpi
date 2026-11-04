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

### What you need

- 2 HUB75 RGB panels, 64x32, with the power cable they come with
- A way to hook them up to the Pi, either:
  - the Adafruit RGB Matrix Bonnet, plus a 16-pin ribbon cable with a socket on both ends for each panel, or
  - no bonnet: the 16-wire cable Waveshare panels come with (a ribbon socket on one end, 16 jumper ends on the other) goes straight onto the Pi's pins, plus one socket-to-socket ribbon to chain the second panel. See [Without the bonnet](#without-the-bonnet).
- A 5V 4A power supply with a 5.5x2.1 mm barrel plug, for the panels
- The Pi's normal USB-C supply. Use a strong one (the official 27W); a weak one causes errors here (see the table at the end).

### Wiring with the bonnet

Do all of this with everything unplugged.

1. Push the bonnet onto the Pi's 40-pin header. Line it up with every pin and push it all the way down.
2. Run a ribbon cable from the bonnet to the first panel's **IN** connector. On the back of each panel, the arrows point away from IN and toward OUT.
3. Run the second ribbon cable from the first panel's **OUT** to the second panel's **IN**.
4. Panel power: the power cable's red lead goes into the bonnet's **+** screw terminal and the black lead into **−**. (If each panel came with its own cable, both reds go into **+** and both blacks into **−**.) Tighten the screws and give each wire a tug.
5. Plug the 5V 4A supply's barrel plug into the bonnet's barrel jack, but don't plug the supply into the wall yet.

One 4A supply for both panels is fine here. Adafruit runs two panels off one 4A adapter, and this sign is mostly dark and capped at 200.

### Power-up order with the bonnet

Plug in the Pi's USB-C first, then plug in the panel supply. To turn it off, run `sudo poweroff`, wait for the green light to stop blinking, then unplug both.

### Without the bonnet

You can skip the bonnet and run the panel's cable straight to the Pi's pins. The bonnet's main job is boosting the Pi's 3.3 V signals to the 5 V the panels are built for. Most panels read 3.3 V just fine, though, and Waveshare's own guide wires their panels straight to the Pi. The sign code doesn't change either: wire it to the same pins the bonnet uses (the table below) and leave `PANEL_PINOUT` alone.

The catch is that a panel that's picky about 3.3 V shows random sparkles or flicker. If yours does, the bonnet fixes it, and nothing else here changes.

#### The cable

Waveshare panels come with a 16-wire rainbow cable: a black ribbon socket on one end and 16 separate jumper ends on the other. The socket goes on the panel, and the jumper ends go on the Pi.

Each wire's number is its spot in the flat ribbon. Wire 1 is at the edge marked by a tiny triangle on the socket, and it's normally brown. Count across from there, and wire N lands on the panel's pin N. The colors repeat after ten, so wires 11 to 16 are brown, red, orange, yellow, green and blue again. Where the jumper ends fan out, trace each one back to its spot in the ribbon.

Forget what wire colors usually mean here: wire 10 (black) carries a signal, and wires 4 (yellow) and 16 (blue) are ground.

#### Pi pin numbers

The table uses the header's own pin numbers (1 to 40), not GPIO numbers. Pin 1 is the corner pin at the end away from the USB ports. Odd numbers run along the inner row and even numbers along the outer edge, so 39 and 40 are the last pair, next to the USB ports. Run `pinout` on the Pi to see a map.

#### Check the cable's direction first

This is the one mistake that can hurt the Pi. If wire 1 is really on the other edge, two of the Pi's pins end up pushing straight into ground. Checking takes a minute, and the panel doesn't need power for it.

1. With the Pi off, push the socket onto the first panel's **IN** connector. It only fits one way. IN is the connector the arrows on the back point away from.
2. Put just two jumpers on the Pi: wire 16 (blue, at the edge away from brown) on pin 39, and wire 4 (yellow) on pin 29.
3. Boot the Pi and run:

```bash
sudo pinctrl set 5 ip pu
sudo pinctrl get 5
```

If the line ends in `lo`, you're good. Wires 4 and 16 are both the panel's ground, so they pulled the pin low. If it ends in `hi`, the cable counts from the other edge: the blue edge is wire 1, and the colors in the table won't match. Go by position instead, and run the check again with the new wires 4 and 16.

Shut the Pi down (`sudo poweroff`, wait for the green light to stop blinking, unplug it) before you wire the rest.

#### Wiring

| Wire | Color | Panel pin | Pi pin | GPIO |
| --- | --- | --- | --- | --- |
| 1 | brown | R1 | 29 | 5 |
| 2 | red | G1 | 33 | 13 |
| 3 | orange | B1 | 31 | 6 |
| 4 | yellow | GND | 30 | ground |
| 5 | green | R2 | 32 | 12 |
| 6 | blue | G2 | 36 | 16 |
| 7 | purple | B2 | 16 | 23 |
| 8 | gray | E | none, leave it off | |
| 9 | white | A | 15 | 22 |
| 10 | black | B | 37 | 26 |
| 11 | brown | C | 13 | 27 |
| 12 | red | D | 38 | 20 |
| 13 | orange | CLK | 11 | 17 |
| 14 | yellow | LAT | 40 | 21 |
| 15 | green | OE | 7 | 4 |
| 16 | blue | GND | 39 | ground |

Wire 8 (E) is only for 64-row panels. Leave its jumper end hanging; the plastic covers the metal.

#### Power

The panels never get power from the Pi. Its 5V pins can't supply anywhere near enough current.

1. The power cable has two white plugs (one per panel) and red and black wires with fork ends. Push one white plug into the panel's **POWER** connector. It's keyed.
2. The fork ends go into the green screw terminal on the little barrel-jack adapter from the box: red under **+**, black under **−** (marked on the adapter). Tighten the screws and give each wire a tug.
3. The 5V 4A supply plugs into the adapter.

The two ground jumpers (wires 4 and 16) are the only thing tying the Pi's ground to the panel's, so both have to be on.

To chain the second panel, run a socket-to-socket ribbon from the first panel's **OUT** to the second panel's **IN**, and push the power cable's second white plug into the second panel.

Plug in the panel supply first, then the Pi, so the Pi never pushes signals into a panel with no power. To turn it off, run `sudo poweroff`, wait for the green light to stop blinking, then unplug both.

The one-time setup and the smoke test below are exactly the same without the bonnet.

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
groups            # should include gpio
```

If `gpio` is missing from `groups`, run `sudo usermod -aG gpio dayoon`, then log out and back in.

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
| Garbage, flicker, or one panel copies the other | Check the cables go Pi (or bonnet) → IN, OUT → IN (follow the arrows) and are pushed all the way in. Make sure nothing else is using the pins (stop the `dayanpi` service). |
| Panels flicker or the Pi reboots on bright pages | The supply is too weak or a screw terminal is loose. |
| Panel stays dark (no bonnet) | Is the panel supply plugged in? Is the socket on **IN**, not OUT? Then recheck every jumper against the table. |
| Random sparkles or flicker (no bonnet) | Make sure both ground wires are on and every jumper is pushed all the way down. If it doesn't go away, the panel is picky about 3.3 V signals, and the bonnet fixes that. |

## How the app drives it

`DAYANPI_SIGN` in `/etc/dayanpi.env` picks where the sign goes. With `preview` (the default) or `panel`, the app renders it a few times a second and the dashboard shows the preview in the LED sign card next to the camera:

| Value | What |
| --- | --- |
| `preview` (default) | Website preview only |
| `panel` | Website preview **and** the real panels through the Matrix Bonnet |
| `off` | Nothing, not even the preview |

What it shows is decided in `dayanpi/sign/controller.py`: the **Now** page by default, **Today** and **Day done** as you flip pages with the one-hand gestures or the **Flip sign page** button on the dashboard (they fall back to **Now** after 20 s), callouts scrolling across whatever page is up, the **Day done** page by itself for 15 minutes after the day-done callout, and a dimmer "ambient" sign during a work block and at night (11 pm to 7 am). `GET /api/sign.png` is the preview image on its own.
