import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useTalk } from "@/hooks/useTalk";
import { EVERYONE } from "@/lib/talk";

// Just enough of Chrome's WebCodecs, mic, Web Audio and WebSocket for the hook: what it asks for and what it sends.
class FakeSocket {
  static OPEN = 1;
  static opened: FakeSocket[] = [];
  readyState = 1;
  onopen: (() => void) | null = null;
  binaryType = "blob";
  sent: (number[] | string)[] = [];
  onmessage: ((event: { data: ArrayBuffer }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  constructor(public url: string) {
    FakeSocket.opened.push(this);
  }
  send(data: Uint8Array | string) {
    this.sent.push(typeof data === "string" ? data : [...data]);
  }
  close() {
    this.readyState = 3;
  }
}

class FakeEncoder {
  static isConfigSupported = async () => ({ supported: true });
  state = "unconfigured";
  constructor(private init: { output: (chunk: { byteLength: number; copyTo: (into: Uint8Array) => void }) => void }) {}
  configure() {
    this.state = "configured";
  }
  encode() {
    this.init.output({ byteLength: 2, copyTo: (into) => into.set([0xaa, 0xbb]) });
  }
  close() {
    this.state = "closed";
  }
}

class FakeDecoder {
  static isConfigSupported = async () => ({ supported: true });
  static decoded = 0;
  state = "configured";
  configure() {}
  decode() {
    FakeDecoder.decoded += 1;
  }
  close() {
    this.state = "closed";
  }
}

let micFrames: ReadableStreamDefaultController<{ sampleRate: number; numberOfChannels: number; close: () => void }> | null = null;
const track = { stop: vi.fn(() => micFrames?.close()) };
const getUserMedia = vi.fn(async () => ({ getAudioTracks: () => [track] }));

beforeEach(() => {
  FakeSocket.opened = [];
  FakeDecoder.decoded = 0;
  track.stop.mockClear();
  getUserMedia.mockClear();
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("AudioEncoder", FakeEncoder);
  vi.stubGlobal("AudioDecoder", FakeDecoder);
  vi.stubGlobal("EncodedAudioChunk", class {});
  vi.stubGlobal("AudioWorkletNode", class {
    port = { postMessage: () => {} };
    connect() {}
  });
  vi.stubGlobal("AudioContext", class {
    audioWorklet = { addModule: async () => {} };
    destination = {};
    resume = async () => {};
    close = async () => {};
  });
  vi.stubGlobal("MediaStreamTrackProcessor", class {
    readable = new ReadableStream({ start: (controller) => void (micFrames = controller) });
  });
  vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia } });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("does nothing without WebCodecs Opus: no socket, and it says so", async () => {
  vi.stubGlobal("AudioEncoder", undefined);
  const { result } = renderHook(() => useTalk());
  await waitFor(() => expect(result.current.supported).toBe(false));
  expect(FakeSocket.opened).toHaveLength(0);
});

it("hears the room on one socket, and knows who's talking until they go quiet", async () => {
  const { result } = renderHook(() => useTalk());
  await waitFor(() => expect(FakeSocket.opened).toHaveLength(1));
  const socket = FakeSocket.opened[0];
  expect(socket.url).toBe(`ws://${window.location.host}/api/talk`);
  expect(socket.binaryType).toBe("arraybuffer");
  act(() => socket.onmessage?.({ data: new Uint8Array([1, 3, 115, 97, 109, 9, 9]).buffer }));
  expect(result.current.talking).toEqual({ sam: "you" });
  expect(FakeDecoder.decoded).toBe(1);
  expect(getUserMedia).not.toHaveBeenCalled(); // hearing never asks for the mic
  await waitFor(() => expect(result.current.talking).toEqual({}), { timeout: 2000 });
});

it("asks for the mic only when you talk, sends each frame for whoever it's for, and lets go of it on stop", async () => {
  const { result } = renderHook(() => useTalk());
  await waitFor(() => expect(FakeSocket.opened).toHaveLength(1));
  expect(getUserMedia).not.toHaveBeenCalled();
  act(() => result.current.talkTo(EVERYONE));
  await waitFor(() => expect(micFrames).not.toBeNull());
  const speak = async () => {
    micFrames?.enqueue({ sampleRate: 48_000, numberOfChannels: 1, close: () => {} });
    await new Promise((resolve) => setTimeout(resolve, 0));
  };
  await act(speak);
  act(() => result.current.talkTo("sam"));
  await act(speak);
  expect(FakeSocket.opened[0].sent).toEqual([
    [0, 0xaa, 0xbb],
    [3, 115, 97, 109, 0xaa, 0xbb],
  ]);
  expect(getUserMedia).toHaveBeenCalledTimes(1); // switching who it's for keeps the same mic
  act(() => result.current.stop());
  expect(result.current.target).toBeNull();
  expect(track.stop).toHaveBeenCalled();
});

it("tries again after a dropped socket, but not when the Pi said not to", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  renderHook(() => useTalk());
  await waitFor(() => expect(FakeSocket.opened).toHaveLength(1));
  act(() => FakeSocket.opened[0].onclose?.({ code: 1006 }));
  await act(async () => vi.advanceTimersByTime(3100));
  expect(FakeSocket.opened).toHaveLength(2);
  act(() => FakeSocket.opened[1].onclose?.({ code: 4001 })); // a newer tab took over
  await act(async () => vi.advanceTimersByTime(5000));
  expect(FakeSocket.opened).toHaveLength(2);
});

it("opens one socket, not a second when Opus support comes back after signaling turned it on", async () => {
  renderHook(() => useTalk(true));
  await waitFor(() => expect(FakeSocket.opened).toHaveLength(1));
  await new Promise((resolve) => setTimeout(resolve, 50)); // Opus has come back supported by now
  expect(FakeSocket.opened).toHaveLength(1);
});

it("keeps the new socket when the one it replaced closes late", async () => {
  vi.stubGlobal("AudioEncoder", undefined); // no talk here, so only signaling wants the socket
  const { result, rerender } = renderHook(({ signaling }) => useTalk(signaling), { initialProps: { signaling: true } });
  await waitFor(() => expect(FakeSocket.opened).toHaveLength(1));
  rerender({ signaling: false });
  rerender({ signaling: true });
  await waitFor(() => expect(FakeSocket.opened).toHaveLength(2));
  const [old, current] = FakeSocket.opened;
  act(() => current.onopen?.());
  act(() => old.onclose?.({ code: 4001 }));
  expect(result.current.connected).toBe(true);
  act(() => result.current.sendSignal("sam", { hello: true }));
  expect(current.sent).toEqual([JSON.stringify({ to: "sam", signal: { hello: true } })]); // on the socket that's open
});
