import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useSmoothVideo } from "@/hooks/useSmoothVideo";
import type { SignalListener, Talk } from "@/hooks/useTalk";
import type { RtcReply } from "@/lib/smoothVideo";

// Just enough of RTCPeerConnection to see what the hook asks of it.
class FakeConnection {
  static made: FakeConnection[] = [];
  transceivers: { direction: string; sender: { replaceTrack: ReturnType<typeof vi.fn>; getParameters: () => RTCRtpSendParameters; setParameters: ReturnType<typeof vi.fn> } }[] = [];
  localDescription: (RTCSessionDescriptionInit & { toJSON: () => RTCSessionDescriptionInit }) | null = null;
  remoteDescription: RTCSessionDescriptionInit | null = null;
  connectionState = "new";
  added: RTCIceCandidateInit[] = [];
  closed = false;
  onicecandidate: ((event: { candidate: null }) => void) | null = null;
  ontrack: ((event: { streams: MediaStream[]; track: MediaStreamTrack }) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  constructor(public config: RTCConfiguration) {
    FakeConnection.made.push(this);
  }
  private makeTransceiver(direction: string) {
    const sender = { replaceTrack: vi.fn(async () => {}), getParameters: () => ({ encodings: [{}] }) as unknown as RTCRtpSendParameters, setParameters: vi.fn(async () => {}) };
    this.transceivers.push({ direction, sender });
  }
  addTransceiver(_kind: string, init: { direction: string }) {
    this.makeTransceiver(init.direction);
  }
  getTransceivers() {
    return this.transceivers;
  }
  async createOffer() {
    return { type: "offer" as const, sdp: "offer-sdp" };
  }
  async createAnswer() {
    return { type: "answer" as const, sdp: "answer-sdp" };
  }
  async setLocalDescription(description: RTCSessionDescriptionInit) {
    await Promise.resolve(); // like Chrome, it finishes later, and a connection closed by then throws
    if (this.closed) {
      throw new Error("InvalidStateError: the connection is closed");
    }
    this.localDescription = { ...description, toJSON: () => description };
  }
  async setRemoteDescription(description: RTCSessionDescriptionInit) {
    this.remoteDescription = description;
    if (description.type === "offer") {
      this.makeTransceiver("recvonly");
    }
  }
  async addIceCandidate(candidate: RTCIceCandidateInit) {
    this.added.push(candidate);
  }
  close() {
    this.closed = true;
  }
}

const RTC_ON: RtcReply = { smooth_video: true, ice_servers: [{ urls: "stun:example.test:3478" }] };
const camera = { kind: "video", getSettings: () => ({ width: 1280, height: 720 }), applyConstraints: vi.fn() } as unknown as MediaStreamTrack;
let listeners: SignalListener[] = [];
const sent: [string, object][] = [];
const talk = {
  connected: true,
  sendSignal: (to: string, signal: object) => void sent.push([to, signal]),
  listenSignals: (listener: SignalListener) => {
    listeners.push(listener);
    return () => void (listeners = listeners.filter((known) => known !== listener));
  },
} as unknown as Talk;
const getUserMedia = vi.fn();

beforeEach(() => {
  FakeConnection.made = [];
  listeners = [];
  sent.length = 0;
  vi.stubGlobal("RTCPeerConnection", FakeConnection);
  vi.stubGlobal("MediaStream", class {});
  vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia } });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const hear = (from: string, signal: object) => act(() => listeners.forEach((listener) => listener(from, signal)));

it("makes no connection at all while the Pi has smooth video off", () => {
  renderHook(() => useSmoothVideo({ smooth_video: false, ice_servers: [] }, { talk, me: "al", peers: ["sam"], track: camera }));
  renderHook(() => useSmoothVideo(null, { talk, me: "al", peers: ["sam"], track: camera }));
  expect(FakeConnection.made).toHaveLength(0);
  expect(sent).toEqual([]);
});

it("has the offering side send an offer with the Pi's ICE servers and the camera's own track, and the other ask for one", async () => {
  renderHook(() => useSmoothVideo(RTC_ON, { talk, me: "al", peers: ["sam"], track: camera }));
  await waitFor(() => expect(sent.some(([, signal]) => "description" in signal)).toBe(true));
  const [connection] = FakeConnection.made;
  expect(connection.config.iceServers).toEqual(RTC_ON.ice_servers);
  expect(sent.at(-1)).toEqual(["sam", { session: expect.any(String), description: { type: "offer", sdp: "offer-sdp" } }]);
  expect(connection.transceivers[0].sender.replaceTrack).toHaveBeenCalledWith(camera); // the tracker's own track
  await waitFor(() => expect(connection.transceivers[0].sender.setParameters).toHaveBeenCalled());
  expect(connection.transceivers[0].sender.setParameters.mock.calls[0][0].encodings[0]).toEqual({ maxBitrate: 600_000, maxFramerate: 30, scaleResolutionDownBy: 2 });

  sent.length = 0;
  renderHook(() => useSmoothVideo(RTC_ON, { talk, me: "zed", peers: ["sam"], track: camera }));
  expect(sent).toEqual([["sam", { hello: true }]]);
});

it("drops your camera from every connection when you hide or go away, and picks it up when you're back", async () => {
  const { rerender } = renderHook(({ track }) => useSmoothVideo(RTC_ON, { talk, me: "al", peers: ["sam", "zed"], track }), { initialProps: { track: camera as MediaStreamTrack | null } });
  await waitFor(() => expect(FakeConnection.made).toHaveLength(2));
  rerender({ track: null });
  for (const connection of FakeConnection.made) {
    expect(connection.transceivers[0].sender.replaceTrack).toHaveBeenLastCalledWith(null);
  }
  rerender({ track: camera });
  await waitFor(() => expect(FakeConnection.made[0].transceivers[0].sender.replaceTrack).toHaveBeenLastCalledWith(camera));
});

it("answers an offer, uses candidates that came early, and ignores anyone who isn't here", async () => {
  renderHook(() => useSmoothVideo(RTC_ON, { talk, me: "zed", peers: ["sam"], track: camera }));
  hear("stranger", { session: "s0", description: { type: "offer", sdp: "x" } });
  expect(FakeConnection.made).toHaveLength(0);
  hear("sam", { session: "s1", description: { type: "offer", sdp: "offer-sdp" } });
  await waitFor(() => expect(sent.at(-1)).toEqual(["sam", { session: "s1", description: { type: "answer", sdp: "answer-sdp" } }]));
  const [connection] = FakeConnection.made;
  expect(connection.transceivers[0].direction).toBe("sendrecv");
  hear("sam", { session: "s1", candidate: { candidate: "c1" } });
  hear("sam", { session: "old", candidate: { candidate: "stale" } });
  expect(connection.added).toEqual([{ candidate: "c1" }]);
});

it("takes the answer only for the offer it's for, so a crossed hello can't tie two setups together", async () => {
  renderHook(() => useSmoothVideo(RTC_ON, { talk, me: "al", peers: ["sam"], track: camera }));
  await waitFor(() => expect(sent.some(([, signal]) => "description" in signal)).toBe(true));
  hear("sam", { hello: true }); // arrives while the first offer is out: a fresh offer replaces it
  await waitFor(() => expect(FakeConnection.made).toHaveLength(2));
  const [first, second] = FakeConnection.made;
  hear("sam", { session: "not-this-one", description: { type: "answer", sdp: "answer-sdp" } });
  expect(second.remoteDescription).toBeNull();
  const session = (sent.filter(([, signal]) => "description" in signal).at(-1)?.[1] as { session: string }).session;
  hear("sam", { session, description: { type: "answer", sdp: "answer-sdp" } });
  await waitFor(() => expect(second.remoteDescription).toEqual({ type: "answer", sdp: "answer-sdp" }));
  expect(first.closed).toBe(true);
});

it("falls back to the picture when a connection fails, and never opens a camera or changes the track", async () => {
  const { result } = renderHook(() => useSmoothVideo(RTC_ON, { talk, me: "al", peers: ["sam"], track: camera }));
  await waitFor(() => expect(FakeConnection.made).toHaveLength(1));
  const [connection] = FakeConnection.made;
  const theirs = {} as MediaStream;
  act(() => connection.ontrack?.({ streams: [theirs], track: {} as MediaStreamTrack }));
  expect(result.current).toEqual({ sam: theirs });
  connection.connectionState = "failed";
  act(() => connection.onconnectionstatechange?.());
  expect(result.current).toEqual({}); // the seat goes back to the picture a second
  expect(connection.closed).toBe(true);
  expect(getUserMedia).not.toHaveBeenCalled();
  expect(camera.applyConstraints).not.toHaveBeenCalled();
});

it("doesn't let a setup that a newer offer replaced take the new connection down with it", async () => {
  renderHook(() => useSmoothVideo(RTC_ON, { talk, me: "al", peers: ["sam"], track: camera }));
  hear("sam", { hello: true }); // lands while the first offer is still being made
  await waitFor(() => expect(FakeConnection.made.length).toBeGreaterThanOrEqual(2));
  const newest = FakeConnection.made.at(-1)!;
  await waitFor(() => expect(newest.localDescription).not.toBeNull());
  expect(newest.closed).toBe(false);
});

it("gives up on a connection that never comes up and tries again, and asks again for an offer that never came", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  renderHook(() => useSmoothVideo(RTC_ON, { talk, me: "al", peers: ["sam"], track: camera }));
  await waitFor(() => expect(FakeConnection.made).toHaveLength(1)); // its offer is lost: no answer ever comes
  await act(async () => vi.advanceTimersByTime(20_000));
  expect(FakeConnection.made[0].closed).toBe(true);
  await act(async () => vi.advanceTimersByTime(15_000));
  await waitFor(() => expect(FakeConnection.made).toHaveLength(2)); // a fresh offer

  sent.length = 0;
  renderHook(() => useSmoothVideo(RTC_ON, { talk, me: "zed", peers: ["sam"], track: camera }));
  expect(sent).toEqual([["sam", { hello: true }]]);
  await act(async () => vi.advanceTimersByTime(15_000));
  expect(sent).toEqual([["sam", { hello: true }], ["sam", { hello: true }]]);
  vi.useRealTimers();
});
