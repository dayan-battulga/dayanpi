import { expect, it } from "vitest";
import { describeSeatLine, findDoneShare, listSharedPieces, orderSeats, summarizeRoom } from "@/lib/room";
import { makeSeat } from "@/test/fixtures";

const SAM = makeSeat({ username: "sam", name: "Sam", state: "phone", focus_seconds: 6480 });
const ALEX = makeSeat({ username: "alex", name: "Alex", state: "away", focus_seconds: 7500 });
const ME = makeSeat({ focus_seconds: 11538 });

it("puts your own seat first and keeps everyone else in the order they joined", () => {
  expect(orderSeats([SAM, ME, ALEX], "dayan").map((seat) => seat.username)).toEqual(["dayan", "sam", "alex"]);
});

it("adds up today's focus of everyone here who shares it", () => {
  const room = summarizeRoom([ME, SAM, ALEX]);
  expect(room.focusSeconds).toBe(11538 + 6480 + 7500); // the mockup's 7h 05m
  expect(room.caption).toBe("3 here · focused together today");
  expect(room.hereLabel).toBe("Here now: Dayan, Sam, and Alex");

  const { focus_seconds: _hidden, ...privateSam } = SAM;
  const offline = { ...ALEX, here: false, state: "offline" as const, seconds_in_state: null };
  const fewer = summarizeRoom([ME, privateSam, offline]);
  expect(fewer.focusSeconds).toBe(11538); // Sam keeps it private and Alex isn't here
  expect(fewer.caption).toBe("2 here · focused together today");
  expect(summarizeRoom([ME]).caption).toBe("focused today");
  expect(summarizeRoom([ME]).hereLabel).toBe("Here now: just you");
});

it("writes the line under a seat from what they share", () => {
  expect(describeSeatLine(makeSeat({ app: "Code" }))).toEqual({ todo: "finish the report", app: "Code" });
  expect(describeSeatLine(makeSeat({ state: "phone", app: "Chrome", site: "github.com" }))).toEqual({ todo: "finish the report · paused", app: "github.com in Chrome" });
  expect(describeSeatLine(makeSeat({ todos: undefined }))).toEqual({ todo: null, app: null });
  expect(describeSeatLine(makeSeat({ todos: { current: null, done: 0, total: 2 }, app: null }))).toEqual({ todo: null, app: null });
});

it("fills the done bar with the share of to-dos done, and shows none without a list", () => {
  expect(findDoneShare(makeSeat())).toBe(25);
  expect(findDoneShare(makeSeat({ todos: { current: null, done: 0, total: 0 } }))).toBeNull();
  expect(findDoneShare(makeSeat({ todos: undefined }))).toBeNull();
});

it("lists the preview's pieces in Settings' order, only what the seat carries", () => {
  expect(listSharedPieces(makeSeat({ focus_seconds: 11538, app: "Code", site: "github.com" }))).toEqual([
    { key: "focus", text: "3h 12m today" },
    { key: "todos", text: "finish the report" },
    { key: "apps", text: "Code" },
    { key: "sites", text: "github.com" },
  ]);
  expect(listSharedPieces(makeSeat({ focus_seconds: undefined, todos: undefined }))).toEqual([]);
});
