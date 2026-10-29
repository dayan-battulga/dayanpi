# Mac helper: which app is in front

A tiny script for the focus tracker. The Pi's camera can tell whether I'm working, on my phone, or away. This script adds *what* I'm doing on the Mac (Code, Slack, Google Chrome...), so "working" can be split into coding, docs, browsing and so on.

Every 2 seconds it asks macOS for the name of the app in front. When that changes, it sends the name to the Pi (`POST /api/mac/app`). It also re-sends the current app every 60 seconds as a heartbeat, so the Pi knows the Mac is still there. A locked screen shows up as `Locked`.

If the Pi can't be reached (Tailscale off, Pi rebooting), it doesn't crash. It waits and tries again (2 s, 4 s, 8 s... up to a minute between tries), and it only ever sends whatever app is in front *by then*, so nothing piles up.

It's plain Python with nothing to install, so macOS's own `/usr/bin/python3` runs it.

## Privacy

It only sends the app's name, like `{"app": "Slack"}`. No window titles, no tab names or URLs, no screenshots, no keystrokes, nothing about what's inside the app. It goes to your Pi over Tailscale and nowhere else. The log on the Mac (`~/Library/Logs/dayanpi-mac-helper.log`) has the same app names and nothing more. Your password stays in the Keychain and never shows up in the log.

## What you need

- The Tailscale app connected on the Mac, same as for opening the dashboard.
- The dashboard login (`DAYANPI_USER` / `DAYANPI_PASSWORD` from `/etc/dayanpi.env` on the Pi).
- `/usr/bin/python3`, which comes with Xcode's command line tools. Run `/usr/bin/python3 --version`. If it offers to install the tools, say yes.
- The Pi running a version of the app that has `/api/mac/app`.

## 1. Copy it out of Desktop

```bash
mkdir -p ~/dayanpi-mac-helper
cd ~/Desktop/code/projects/site-page/mac_helper
cp dayanpi_mac_helper.py com.dayanpi.machelper.plist ~/dayanpi-mac-helper/
```

For the hand tests in step 3 you can also just `cd ~/Desktop/code/projects/site-page/mac_helper` and run it from the repo. The background job can't, though: macOS guards `~/Desktop`, `~/Documents` and `~/Downloads`, and a background `python3` reading a script in there usually just fails with "Operation not permitted". The LaunchAgent expects `~/dayanpi-mac-helper`.

## 2. Put the password in the Keychain

Swap `yourname` for your dashboard username, here and in every command below:

```bash
security add-generic-password -s dayanpi -a yourname -w
```

With `-w` last and nothing after it, `security` asks for the password instead of taking it on the command line, so it never lands in your shell history. Nothing shows up while you type; that's normal.

- Check it's there (this shows the item's details, not the password): `security find-generic-password -s dayanpi -a yourname`
- Changed the password on the Pi? Run the same add command with `-U` to overwrite it: `security add-generic-password -U -s dayanpi -a yourname -w`. A running helper picks up the new one by itself after its next 401.
- Stick to plain keyboard characters. `security` hands back passwords with emoji or accented letters as hex, and then the login fails.

## 3. Try it by hand

```bash
cd ~/dayanpi-mac-helper
/usr/bin/python3 dayanpi_mac_helper.py --once
```

It prints the app in front (probably `Terminal`, since you just typed in it) and quits. No network, no password needed.

Then the dry run. It keeps watching but only prints what it *would* send:

```bash
/usr/bin/python3 dayanpi_mac_helper.py --dry-run
```

Click between a few apps. You should see a `would POST {"app": ...}` line for each switch, plus the same app again after a minute (the heartbeat). `Ctrl+C` to stop.

Last, the real thing, still in the foreground:

```bash
DAYANPI_USER=yourname /usr/bin/python3 dayanpi_mac_helper.py
```

Switch apps a few times. A `front app: ...` line per switch and no warnings means the Pi is taking them. `Ctrl+C` to stop.

**Permission pop-up:** the script asks `lsappinfo` first, which needs no permission. Only if that fails does it fall back to AppleScript (`osascript` asking System Events). The first time that happens, macOS asks whether Terminal (or `python3`, when it runs in the background) may control System Events. Click OK. Missed it or said no? System Settings → Privacy & Security → Automation.

## 4. Run it in the background (LaunchAgent)

Plists don't understand `~` or `$HOME`, so the plist in this folder is a template with placeholders. This line fills them in and drops the result into `~/Library/LaunchAgents`:

```bash
sed -e "s|__HOME__|$HOME|g" -e "s|__DAYANPI_USER__|yourname|g" -e "s|__DAYANPI_URL__|https://dayoon.tail279594.ts.net|g" ~/dayanpi-mac-helper/com.dayanpi.machelper.plist > ~/Library/LaunchAgents/com.dayanpi.machelper.plist
```

Then check it and start it:

```bash
plutil -lint ~/Library/LaunchAgents/com.dayanpi.machelper.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.dayanpi.machelper.plist
```

`plutil -lint` should say `OK`. From now on it starts by itself when you log in, and launchd restarts it if it ever dies.

macOS may pop up a "Background Items Added" notice. It shows up as `python3` in System Settings → General → Login Items & Extensions. Leave it switched on.

## Checking on it

```bash
launchctl print gui/$(id -u)/com.dayanpi.machelper | grep -E "state =|pid =|last exit code"
tail -f ~/Library/Logs/dayanpi-mac-helper.log
```

You want `state = running`. The log gets a line per app switch, plus warnings when something's off:

```text
2026-10-29 10:14:02 INFO front app: Code
2026-10-29 10:14:40 INFO front app: Slack
2026-10-29 10:20:11 WARNING couldn't send 'Slack', trying again in 2 s: can't reach the Pi (...). Is Tailscale connected and the dayanpi service running?
2026-10-29 10:20:15 INFO reached the Pi again after 2 failed tries
```

It grows slowly. Empty it whenever you like: `: > ~/Library/Logs/dayanpi-mac-helper.log`

## Updating

After a `git pull` that changed the helper:

```bash
cp ~/Desktop/code/projects/site-page/mac_helper/dayanpi_mac_helper.py ~/dayanpi-mac-helper/
launchctl kickstart -k gui/$(id -u)/com.dayanpi.machelper
```

`kickstart -k` restarts it with the new script. If the plist changed too, boot it out (below), redo the `sed` line from step 4, and bootstrap it again.

## Stopping and uninstalling

Stop it for now:

```bash
launchctl bootout gui/$(id -u)/com.dayanpi.machelper
```

It comes back at your next login unless you also delete the plist. To remove everything:

```bash
launchctl bootout gui/$(id -u)/com.dayanpi.machelper
rm ~/Library/LaunchAgents/com.dayanpi.machelper.plist
rm -r ~/dayanpi-mac-helper
rm ~/Library/Logs/dayanpi-mac-helper.log
security delete-generic-password -s dayanpi -a yourname
```

The last line deletes the saved password too; skip it if you want to keep it.

## When something's off

| What you see | What to do |
| --- | --- |
| `DAYANPI_USER isn't set` | By hand: put `DAYANPI_USER=yourname` in front of the command. Background: redo the `sed` line with your name |
| `No dashboard password in the Keychain` | Step 2. The `-a` name has to match `DAYANPI_USER` exactly |
| `the Pi said 401` | Wrong username or password. Fix it with the `-U` command from step 2; the helper rereads it by itself |
| `can't reach the Pi` | Is Tailscale connected? Does https://dayoon.tail279594.ts.net/ open in the browser? Is the `dayanpi` service running? |
| `the Pi answered HTTP 404` | The Pi's code doesn't have `/api/mac/app` yet. Pull and restart the service there |
| `can't tell which app is in front` | Run `--once` in Terminal to see why. Usually it's the System Events permission above |
| `Bootstrap failed: 5: Input/output error` | Usually means it's already loaded. Boot it out, then bootstrap again |
| `Operation not permitted` in the log | The plist points into `~/Desktop` or `~/Documents`. Use the `~/dayanpi-mac-helper` copy |
| The same error every 10 seconds in the log | On setup problems the helper quits and launchd restarts it. Fix what the error names and it carries on by itself |
