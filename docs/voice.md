# Voice (USB speaker)

Part of the dayanpi docs. Setting up and running the Pi is in the [manual](MANUAL.md).

The focus tracker can say things out loud, like "Phone down." or "Break's over.", through a plain USB speaker. The voice is **off** until you turn it on. While it's off, the app just notes in the log that it would have said something (`voice off, would say something (11 characters)`), never the words: a peace sign's message is someone's to-dos. The tracker's own lines show up in full on their `focus callout` line (`focus callout for you, instant_pickup: Phone down.`).

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

## 4. Install Piper

Piper is the voice, and it sounds pretty human. It's a pip package, and it goes into the dashboard's venv:

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

To test it the way the service will run it (as a system service, with no desktop session), try:

```bash
sudo systemd-run --uid=dayoon --wait --pipe /bin/sh -c 'echo "Testing from a system service." | /home/dayoon/Desktop/site-page/dayanpi/.venv/bin/python -m piper --model /home/dayoon/piper-voices/en_US-lessac-medium.onnx --output-raw | aplay -q -D plughw:CARD=Device,DEV=0 -r 22050 -f S16_LE -t raw -'
```

If you hear that, the dashboard will work too. Now turn it on. Open the env file:

```bash
sudo nano /etc/dayanpi.env
```

Add these three lines, with the full path to the voice and your speaker's name:

```
DAYANPI_VOICE=piper
DAYANPI_PIPER_MODEL=/home/dayoon/piper-voices/en_US-lessac-medium.onnx
DAYANPI_AUDIO_DEVICE=plughw:CARD=Device,DEV=0
```

Restart and check the log:

```bash
sudo systemctl restart dayanpi
journalctl -u dayanpi -n 30 --no-pager | grep -i voice
```

You want `voice on: piper through aplay on plughw:CARD=Device,DEV=0`. If the voice can't run (say the voice file is missing), the log says why once and the voice stays off. The rest of the site keeps working either way.

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
| `DAYANPI_VOICE='espeak' isn't one of off, piper` | espeak-ng isn't supported anymore. Set up Piper (step 4), then set `DAYANPI_VOICE=piper` |
| `piper-tts isn't installed in the dashboard's venv` | `.venv/bin/pip install piper-tts` in the dashboard folder, then restart |
| `there's no Piper voice at ...` or `... .onnx.json is missing` | `DAYANPI_PIPER_MODEL` needs the full path, and both files need to be in that folder |
| `Device or resource busy` | Something else has the speaker, usually the desktop's audio. `sudo fuser -v /dev/snd/*` shows who. Close that, or wait a few seconds and it'll let go |
| `Permission denied` | `dayoon` isn't in the `audio` group (step 3) |
| Some other `audio open error` (like `No such device`) | Speaker unplugged, or the name's off (re-check `aplay -L \| grep plughw`). It can also mean `dayoon` isn't in the `audio` group: without it, ALSA can't even look the card up by name |
| Nothing at all | Is `DAYANPI_VOICE` set, and did you restart? Without `DAYANPI_AUDIO_DEVICE`, aplay uses ALSA's default device, which usually isn't the USB speaker. Also check the volume |

## What the peace sign says

Hold up a peace sign (see [Hand signs](focus-tracker.md#hand-signs)) and you get a quick rundown: the time, how long until bed, what's left on your to-do list and what you already finished today. Everyone in the room gets their own: their own to-dos, their own bedtime, and it speaks wherever they picked (below).

Out of the box it's a fixed sentence (the template):

> It's 6 p.m., about 6 hours until bed. You have 3 things to do: finish the report, reply to emails, and do laundry. Done today: read chapter 3 in 40 minutes.

Past bedtime (from bedtime until 5 a.m.) it says it's past your bedtime and to wrap up instead of counting hours. It reads the first 5 to-dos of each list and says how many more.

### Where it speaks: the Pi's speaker or this computer

Settings → **Voice and bedtime** → *The peace sign speaks through*:

- **The Pi's speaker**: aplay, like the rest of this page. Only your desk can pick it (it's in your room), and it's yours until you pick This computer.
- **This computer**: the person's own page plays it. The Pi makes the audio with Piper, with the same voice and settings, but wraps it into a WAV in memory instead of playing it, and keeps it until their page fetches it with `GET /api/voice/clip` (signed in, their own clip only). It's handed out once and gone, or gone after a minute if nobody fetched it. Clips are never written to disk or logged. Every member's peace sign speaks this way. Each person has at most one clip waiting or being made: another one in the meantime is dropped, the same as a full queue. The queue keeps a place for each person's clip on top of the 3 lines the Pi's speaker may have waiting, so nobody's clips can push out anyone else's, or your lines on the speaker.

**Browsers only play sound after a click on the page.** Any click counts, and it lasts as long as the tab is open: the tracker's **Allow camera** on `/track`, or any click anywhere on `/me`. If a browser still says no, the pill shows the words with a small play button, which plays it (it stays up to a minute for that).

**Test the voice** in the same section says a short line ("This is how your peace sign sounds.") through whichever one is picked, pill and all. Clicking it also counts as the click the browser wants. It works once every 10 s per desk, since each test is a Piper run on the Pi; sooner, Settings says how long to wait ("Wait 8 s, then test it again.").

### What the page shows while it talks

Every page you have open shows the same words in a frosted pill just under the top bar, with little green sound bars moving next to them. It rises in when the sign fires, stays while it's being said, and fades away once it's done: on the Pi's speaker that's until aplay finishes; on this computer it goes by the page's own audio, its `playing` and `ended` events. With the voice off, or if nothing could say it, it stays 6 seconds. With Reduce motion on, it just fades in and out and the bars stand still. `/track` shows the pill too and plays the clip there, so a friend with only the tracker open still hears it.

The words come through the live stream as `focus.spoken`: `{"text", "at", "age_s", "speaking", "clip"}`. `speaking` is true from the moment the Pi's speaker queues the phrase until aplay has played it (or it failed); `clip` is true while a clip for this message waits for the page. The text is never written to the journal or the focus log; the log only says which kind you heard.

### Your bedtime

Settings → **Voice and bedtime** → **Bedtime**, everyone their own, kept in their desk's folder (`data/users/<username>/voice.json`). It counts for the next peace sign right away.

Until you pick one, yours comes from `DAYANPI_BEDTIME` in `/etc/dayanpi.env`, as `HH:MM` on a 24-hour clock (default `00:00`, midnight), and everyone else's is midnight. A bedtime after midnight works too: `01:30` means 1:30 a.m., and at 11 p.m. that's two and a half hours away. A `DAYANPI_BEDTIME` that isn't `HH:MM` logs a warning and falls back to midnight.

### With the voice off

`DAYANPI_VOICE=off` (or Piper missing) still works: nobody's speaker or computer plays anything, no clips are made, and the pill shows the words for 6 seconds. Settings → Voice and bedtime says so under Test the voice.

### A friendlier message from a small LLM

With a small model running in [Ollama](https://ollama.com) on the Pi, the peace sign says something more natural instead, written fresh for each person, like:

> It's 6 p.m., so you've got about 6 hours before bed. Three things left: the report, emails and laundry. You already knocked out the reading in 40 minutes, so you can definitely finish these.

1. Install Ollama on the Pi. Its installer sets it up as a service that listens on `127.0.0.1:11434`, only reachable from the Pi itself:

   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```

2. Pull a small model. `llama3.2:1b` is about 1.3 GB and writes about 11 tokens (roughly words) a second on a Pi 5:

   ```bash
   ollama pull llama3.2:1b
   ollama run llama3.2:1b "Say hi in one short sentence."
   ```

3. Turn it on in `/etc/dayanpi.env` and restart:

   ```bash
   DAYANPI_LLM_MODEL=llama3.2:1b
   ```

   ```bash
   sudo systemctl restart dayanpi
   journalctl -u dayanpi -n 50 --no-pager | grep "peace sign"
   ```

   You want `peace sign: writing everyone's messages ahead with llama3.2:1b through Ollama, one at a time`, then a few seconds later `peace sign: LLM messages from llama3.2:1b are ready`.

How it works, so the speaker can answer right away even though the model is slow:

- **Written ahead.** Each person's message gets written in the background every 4 minutes and whenever their to-do list changes, so one is always waiting. The peace sign just speaks it.
- **One at a time.** Everyone's messages go through one queue: a single background thread writes them one after another, so even with 4 people the Pi never runs the model twice at once. With 4 people, a fresh message for everyone takes about 4 times as long; the template covers anyone whose message isn't ready.
- **Never stale.** It only speaks a message written for your current to-do list in the last 5 minutes. Right after you change the list, the template covers the few seconds until the new message is ready.
- **Only the facts.** The model gets the time, the time to bed and the two to-do lists, and is told not to add, drop or rename anything or change any number. Before a message is used, the app checks it: no lists, emojis or markdown, at most 4 sentences, and no number that isn't in the facts. Anything that fails, plus Ollama being off, slow (over 60 s) or erroring, means the template speaks instead. The journal says why.
- **Easy on the Pi.** The model gets 2 of the 4 cores, so the focus checks keep running, and stays loaded between messages: the app asks Ollama to keep it loaded for 15 minutes and asks again every 4, so it doesn't reload each time.
- **Stays on the Pi.** The app only ever talks to `127.0.0.1:11434`. That address is fixed in `dayanpi/hardware/llm.py`, with no setting to point it somewhere else.

Each peace sign's line in the focus log says which one you heard: `"spoken": "llm"` or `"spoken": "template"`.

```bash
grep '"gesture"' data/users/$ME/focus_log/$(date +%F).jsonl   # ME=your username
journalctl -u dayanpi -n 100 --no-pager | grep "peace sign"
```

| Log says | What it means |
| --- | --- |
| `no LLM message (ConnectionRefusedError: ...)` | Ollama isn't running: `sudo systemctl status ollama` |
| `no LLM message (Ollama said 404: model ... not found)` | The model in `DAYANPI_LLM_MODEL` isn't pulled: `ollama list`, then `ollama pull` it |
| `no LLM message (TimeoutError: ...)` | It took over 60 s. The first message after a reboot also has to load the model, so give it one more round |
| `the LLM's message didn't pass` | The model wrote a list, an emoji, too much, or a number that wasn't in the facts. The line only says how long it was, never the words (they're someone's to-dos). Once in a while is fine; all the time means try another model |

To go back to the template, delete the `DAYANPI_LLM_MODEL` line and restart.
