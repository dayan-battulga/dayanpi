// The room's voices (web/src/hooks/useTalk.ts): each talker's decoded sound gets a short queue that starts playing once
// it holds PREBUFFER_S, so a late packet doesn't make a gap, and never holds more than MAX_S, so the delay can't grow.
// Every queue playing is mixed into the one output. An AudioWorklet, so it runs on the audio thread, not the page's.
const PREBUFFER_S = 0.08;
const MAX_S = 0.25;

class TalkPlayer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.voices = new Map();
    this.port.onmessage = ({ data }) => this.add(data.from, data.samples);
  }

  add(from, samples) {
    const voice = this.voices.get(from) ?? { chunks: [], offset: 0, left: 0, playing: false };
    voice.chunks.push(samples);
    voice.left += samples.length;
    while (voice.left > MAX_S * sampleRate && voice.chunks.length > 1) {
      voice.left -= voice.chunks[0].length - voice.offset;
      voice.chunks.shift();
      voice.offset = 0;
    }
    this.voices.set(from, voice);
  }

  process(inputs, outputs) {
    const out = outputs[0][0];
    for (const [from, voice] of this.voices) {
      voice.playing = voice.playing || voice.left >= PREBUFFER_S * sampleRate;
      for (let index = 0; voice.playing && index < out.length; index += 1) {
        const chunk = voice.chunks[0];
        out[index] += chunk[voice.offset];
        voice.offset += 1;
        voice.left -= 1;
        if (voice.offset === chunk.length) {
          voice.chunks.shift();
          voice.offset = 0;
        }
        voice.playing = voice.left > 0;
      }
      if (!voice.playing && voice.left === 0) {
        this.voices.delete(from);
      }
    }
    for (let index = 0; index < out.length; index += 1) {
      out[index] = Math.max(-1, Math.min(1, out[index]));
    }
    return true;
  }
}

registerProcessor("talk-player", TalkPlayer);
