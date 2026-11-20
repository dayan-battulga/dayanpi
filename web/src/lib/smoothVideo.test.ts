import { expect, it } from "vitest";
import { capEncoding, findSendingTrack, isOfferer } from "@/lib/smoothVideo";
import type { FocusStatus } from "@/lib/types";
import { makeFocus } from "@/test/fixtures";

const track = { kind: "video", getSettings: () => ({ width: 1280, height: 720 }) } as unknown as MediaStreamTrack;
const preview = { getVideoTracks: () => [track] } as unknown as MediaStream;
const sharing = { ...makeFocus().sharing!, video: true };
const sending = (focus: Partial<FocusStatus>, enabled = true) => findSendingTrack(makeFocus({ picture_source: "browser", sharing, state: "working", ...focus }), preview, enabled);

it("sends your camera's own track only while smooth video is on, you share video and you're at the desk", () => {
  expect(sending({})).toBe(track); // the very track the tracker reads: never a second camera
  expect(sending({ state: "phone" })).toBe(track);
  expect(sending({}, false)).toBeNull(); // the Pi hasn't turned it on
  expect(sending({ sharing: { ...sharing, video: false } })).toBeNull(); // hidden is hidden
  expect(sending({ state: "away" })).toBeNull();
  expect(sending({ state: "unknown" })).toBeNull();
  expect(sending({ picture_source: "pi" })).toBeNull(); // my seat on the Pi's camera keeps its picture a second
  expect(findSendingTrack(makeFocus({ picture_source: "browser", sharing, state: "working" }), null, true)).toBeNull(); // no camera on
});

it("caps each stream at 640x360, 30 fps and 600 kbps without touching the track", () => {
  expect(capEncoding(track)).toEqual({ maxBitrate: 600_000, maxFramerate: 30, scaleResolutionDownBy: 2 });
  const small = { getSettings: () => ({ width: 640, height: 480 }) } as unknown as MediaStreamTrack;
  expect(capEncoding(small).scaleResolutionDownBy).toBeCloseTo(480 / 360);
});

it("has the same one of each pair make the offer", () => {
  expect([isOfferer("al", "sam"), isOfferer("sam", "al")]).toEqual([true, false]);
});
