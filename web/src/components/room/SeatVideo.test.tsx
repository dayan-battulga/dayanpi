import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { toast } from "sonner";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import type { Seat } from "@/lib/types";
import { answer, serveApi } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { OWNER, makeFocus, makeSeat, makeSnapshot } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

// Sam's camera arriving over smooth video, without any WebRTC: a stream whose one track can go quiet.
const theirs = vi.hoisted(() => ({ videos: {} as Record<string, MediaStream> }));
vi.mock("@/hooks/useSmoothVideo", () => ({ useRtc: () => ({ smooth_video: true, ice_servers: [] }), useSmoothVideo: () => theirs.videos }));

function makeStream() {
  const track = Object.assign(new EventTarget(), { muted: false, readyState: "live", kind: "video" });
  const stream = { getVideoTracks: () => [track] } as unknown as MediaStream;
  return { stream, track };
}

const PICTURE = { at: 1_794_877_937.6 };

function openRoom(seats: Seat[]) {
  serveApi({ "GET /api/me": answer({ user: OWNER }), "GET /api/focus": answer({ segments: [] }) });
  render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
  act(() => FakeEventSource.latest?.send({ ...makeSnapshot(makeFocus()), room: { seats } }));
}

const samSeat = () => screen.getByRole("article", { name: /^Sam,/ });
const startPlaying = (video: HTMLVideoElement) => {
  Object.defineProperty(video, "readyState", { value: 4, configurable: true });
  act(() => video.dispatchEvent(new Event("playing")));
};

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404, headers: new Headers(), json: async () => ({}) })));
});

afterEach(() => {
  vi.unstubAllGlobals();
  theirs.videos = {};
  toast.dismiss();
});

it("plays someone's smooth video over their picture once it runs, and goes back to the picture when it stops", async () => {
  const { stream, track } = makeStream();
  theirs.videos = { sam: stream };
  openRoom([makeSeat(), makeSeat({ username: "sam", name: "Sam", picture: PICTURE })]);
  const video = (await screen.findByRole("article", { name: /^Sam,/ })).querySelector("video.seat-video") as HTMLVideoElement;
  expect(video.srcObject).toBe(stream);
  expect(video).not.toHaveAttribute("data-playing");
  expect(samSeat().querySelector(".seat-picture img, .seat-picture")).not.toBeNull(); // the picture until it plays
  startPlaying(video);
  expect(video).toHaveAttribute("data-playing");
  act(() => {
    track.muted = true; // their camera dropped (hidden, away) or the connection stalled
    track.dispatchEvent(new Event("mute"));
  });
  expect(video).not.toHaveAttribute("data-playing");
});

it("shows nothing of it once the Pi says they're hidden or away, and never on your own seat", async () => {
  const { stream } = makeStream();
  theirs.videos = { sam: stream, [OWNER.username]: stream };
  openRoom([makeSeat({ picture: PICTURE }), makeSeat({ username: "sam", name: "Sam", picture: null })]);
  expect((await screen.findByRole("article", { name: /^Sam,/ })).querySelector("video")).toBeNull(); // their initial
  expect(screen.getByRole("article", { name: /^Dayan,/ }).querySelector("video.seat-video")).toBeNull();
});
