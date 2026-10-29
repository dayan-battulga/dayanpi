# Driving the rover

Part of the dayanpi docs. Setting up and running the Pi is in the [manual](MANUAL.md).

**Paused right now.** The motors are unplugged and the Drive card is hidden. To bring it back, plug the motor wires back in (the pin table is in `CLAUDE.md`), remove `hidden` from the `drive-card` div in `dayanpi/static/index.html`, and add `<script type="module" src="/drive.js"></script>` back after the `app.js` line.

The **Drive** card sits right under the camera. Whatever you press gets sent to the Pi about 7 times a second, and the card shows what's going out (`L` / `R`, from -1 to +1) plus whether you're driving.

One-time check on the Pi: `groups` should include `gpio`, since the service runs as `dayoon` and needs to touch the motor pins.

## On the Mac: keyboard

Click on the page first so it has focus, then hold:

| Keys | What happens |
| --- | --- |
| `W` / `S` | Forward / backward |
| `A` / `D` | Spin left / right in place |
| `W`+`A`, `W`+`D` | Arc left / right while going forward |
| `S`+`A`, `S`+`D` | Same arcs, backing up |
| `W`+`S` or `A`+`D` | Cancel out, nothing moves |

Let go and it stops. Pressing `Cmd`, `Ctrl` or `Alt` also stops it, and so does switching apps or tabs.

## On the phone: the pad

Same idea with the four arrow buttons. Hold ▲ and ◀ with two thumbs to arc left, and so on. Lifting your thumb or sliding it off the button stops that direction. Leaving Safari or locking the phone stops everything.

If the card turns red and says `drive failed`, the Pi didn't get the command (lost signal, logged out, and so on). There are no instant retries: while you're holding a key it keeps sending at the normal pace (one request at a time), and the error clears as soon as one gets through.

## Safety

- **Watchdog.** If the Pi doesn't hear a command for 0.5 s, it stops the wheels on its own. So if your phone dies, the tab crashes or Wi-Fi drops, the robot stops about half a second later.
- **Speed cap.** The Pi never runs the motors above `MAX_SPEED` (60% power by default), no matter what the browser sends.
- **Reversal pause.** Flipping a side from forward to backward stops it for a moment first, so the motors don't slam into reverse.
- **The battery switch is the real emergency stop.** Everything above is software. If the Pi crashes hard (power glitch, kernel panic), the motor pins can stay stuck on whatever they were last doing. If the robot misbehaves, flip the battery switch. Test new code with the wheels up on a box.
- Stopping or restarting the service (`sudo systemctl stop/restart dayanpi`) stops the motors cleanly first.

## Tuning

Change the numbers on the Mac, push, pull on the Pi, and restart the service.

| Knob | File | Default | What it does |
| --- | --- | --- | --- |
| `SPEED_FLOOR` | `dayanpi/hardware/drivetrain.py` | `0.4` | Slowest power that still turns the wheels. If gentle presses just make the motors hum, raise it. |
| `MAX_SPEED` | `dayanpi/hardware/drivetrain.py` | `0.6` | Top power. Raise it slowly, around 0.1 at a time. |
| `DEADZONE` | `dayanpi/hardware/drivetrain.py` | `0.05` | Anything smaller than this counts as zero. |
| `DRIVE_TIMEOUT_S` | `dayanpi/app.py` | `0.5` | How long the watchdog waits before stopping the wheels. |

About the watchdog timeout: the browser sends every 0.15 s, so the timeout has to stay well above that. If driving over cellular feels jerky (keeps stopping and starting), the network is laggy; try `0.8`. Going lower than 0.5 makes it stop faster but stutter more.

The arc turns come from the table at the top of `dayanpi/static/drive.js`. `0.4` there is the inner wheel's input *before* scaling, so it ends up a bit faster than `SPEED_FLOOR`.

## "GPIO busy"

While the service runs, it owns the motor pins. If you try driving them from a Python REPL or script, you'll get "GPIO busy". Stop the service first:

```bash
sudo systemctl stop dayanpi
# ...poke at the motors...
sudo systemctl start dayanpi
```
