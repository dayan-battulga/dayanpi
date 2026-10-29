# Voice (USB speaker)

Part of the dayanpi docs. Setting up and running the Pi is in the [manual](MANUAL.md).

The focus tracker can say things out loud, like "Phone down." or "Break's over.", through a plain USB speaker. The voice is **off** until you turn it on. While it's off, the app just writes what it would have said to the log (`voice off, would say: 'Phone down.'`).

One thing to know first: the dashboard runs as a systemd **system** service, so it can't use the desktop's sound system (PipeWire). It plays straight to the speaker with `aplay` instead. That's why you tell it exactly which device the speaker is.

## 1. Plug in the speaker and find its name

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

## 2. Make sure it plays

```bash
speaker-test -D plughw:CARD=Device,DEV=0 -c 2 -t wav -l 1
```

You should hear "Front left, front right" once. (Leave off `-l 1` and it loops until you press Ctrl+C.) Silent? Check the volume (below) first.

## 3. Let the service use it

The service runs as `dayoon`, and only the `audio` group can open sound devices:

```bash
groups dayoon   # should include "audio"
```

If it's missing:

```bash
sudo usermod -aG audio dayoon
```

The service picks that up the next time it restarts. Your own SSH session only sees it after you log out and back in.

## 4. Quick start: espeak-ng

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

## 5. Nicer voice: Piper

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

## Volume

The speaker has no volume knob, so you set it in software:

```bash
alsamixer
```

Press **F6** and pick the USB speaker, then use the up/down arrows. **Esc** quits. If the level resets after a reboot, save it once you like it:

```bash
sudo alsactl store
```

## Good to know

- Phrases play one at a time. If 3 are already waiting, new ones get dropped. They're about what you're doing right now, so a late one would just be confusing.
- Unplugging the speaker doesn't break anything. Phrases fail (and the log says so) until it's back, no restart needed.
- To turn it off, set `DAYANPI_VOICE=off` in `/etc/dayanpi.env` (or delete the line) and restart. Off is the default.

## When it doesn't talk

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
