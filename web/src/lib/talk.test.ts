import { expect, it } from "vitest";
import { EVERYONE, TALKING_FOR_S, isSameTalking, listTalking, packTalk, readTalk } from "@/lib/talk";

it("packs a frame with who it's for, empty for everyone", () => {
  expect([...packTalk(EVERYONE, new Uint8Array([9, 8]))]).toEqual([0, 9, 8]);
  expect([...packTalk("sam", new Uint8Array([7]))]).toEqual([3, 115, 97, 109, 7]);
});

it("reads who a frame is from and whether it was for everyone or you, and nothing from a scrap", () => {
  const everyone = new Uint8Array([0, 3, 115, 97, 109, 1, 2]).buffer;
  const mine = new Uint8Array([1, 2, 97, 108, 5]).buffer;
  expect(readTalk(everyone)).toEqual({ from: "sam", kind: "everyone", opus: new Uint8Array([1, 2]) });
  expect(readTalk(mine)).toEqual({ from: "al", kind: "you", opus: new Uint8Array([5]) });
  expect(readTalk(new Uint8Array([0, 3, 115]).buffer)).toBeNull();
  expect(readTalk(new ArrayBuffer(0))).toBeNull();
});

it("knows who's talking until they've been quiet a moment, and only changes when someone starts or stops", () => {
  const last = new Map([
    ["sam", { kind: "you" as const, at: 10 }],
    ["al", { kind: "everyone" as const, at: 10 - TALKING_FOR_S - 0.1 }],
  ]);
  expect(listTalking(last, 10)).toEqual({ sam: "you" });
  expect(listTalking(last, 10 + TALKING_FOR_S + 0.1)).toEqual({});
  expect(isSameTalking({ sam: "you" }, { sam: "you" })).toBe(true);
  expect(isSameTalking({ sam: "you" }, { sam: "everyone" })).toBe(false);
  expect(isSameTalking({ sam: "you" }, {})).toBe(false);
});
