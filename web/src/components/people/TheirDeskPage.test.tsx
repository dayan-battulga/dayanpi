import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import type { Seat, TheirDesk } from "@/lib/types";
import { answer, serveApi } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { OWNER, makeSeat, makeSnapshot } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

const NOW = Date.now() / 1000;
const SAM = makeSeat({ username: "sam", name: "Sam", state: "phone", seconds_in_state: 365, shares: ["focus", "todos", "apps", "sites", "video", "history"], app: "Chrome", site: "docs.google.com" });
const PIECES: Omit<TheirDesk, keyof Seat> = {
  here_since: NOW - 3 * 3600,
  today: { working_seconds: 6480, phone_seconds: 840, pickups: 4, segments: [{ state: "working", start: NOW - 7200, end: NOW - 365 }, { state: "phone", start: NOW - 365, end: null }] },
  todo_list: { current: "s1", open: [{ id: "s1", text: "Read chapter 7", seconds: 1440, done_at: null }], done: [{ id: "s2", text: "Vocab quiz", seconds: 2100, done_at: NOW - 900 }] },
  apps: [{ app: "Chrome", total_seconds: 3120 }],
  app_youtube: { Chrome: 540 },
  sites: [{ site: "youtube.com", seconds: 540 }],
  history: { month: "2026-11", today: "2026-11-16", joined_at: NOW - 4 * 86400, days: { "2026-11-14": 210 }, total_minutes: 613 },
  video: true,
};

function ShowPath() {
  return <output aria-label="Path">{useLocation().pathname}</output>;
}

// Sam's desk with only the pieces the Pi sent; the room stream carries Sam's live seat.
function openTheirDesk(seat: Seat, pieces: Partial<TheirDesk>, path = "/people/sam") {
  const desk = { ...seat, here_since: null, ...pieces };
  const sent = serveApi({ "GET /api/me": answer({ user: OWNER }), "GET /api/people/sam": answer(desk), "GET /api/people/nobody": answer({ detail: "nobody by that name" }, 404) });
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <ShowPath />
    </MemoryRouter>,
  );
  FakeEventSource.latest?.send({ ...makeSnapshot(), room: { seats: [makeSeat(), seat] } });
  return sent;
}

const pieceNames = () => Array.from(document.querySelectorAll(".their-piece, .their-video"), (piece) => piece.getAttribute("aria-label"));

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("shows every piece Sam shares, with the Room tab current", async () => {
  openTheirDesk(SAM, PIECES);
  expect(await screen.findByRole("heading", { level: 1, name: "On the phone" })).toBeInTheDocument();
  expect(screen.getByText("Sam shares status, focus time, to-dos, apps, sites, video and history")).toBeInTheDocument();
  expect(screen.getByRole("timer")).toHaveAccessibleName("06:05");
  expect(screen.getByText(/^here since/)).toBeInTheDocument();
  expect(pieceNames()).toEqual(["Sam’s camera", "Sam’s day", "Sam’s to-dos", "Sam’s apps", "Sam’s sites", "Sam’s history"]);
  const day = screen.getByRole("region", { name: "Sam’s day" });
  expect(day).toHaveTextContent("1h 05m focused · 14m on the phone · 4 pickups"); // the live seat's focus time
  expect(within(screen.getByRole("region", { name: "Sam’s apps" })).getByText("52m · 9m YouTube")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Sam’s to-dos" })).getByText("1 of 2 done")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Sam’s history" })).getByText("10h 13m focused since joining", { exact: false })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Nudge Sam" })).toBeEnabled();
  expect(within(screen.getByRole("navigation", { name: "Pages" })).getByRole("link", { name: "Room" })).toHaveAttribute("aria-current", "page");
});

it("fills in with just to-dos and history when that's all Sam shares", async () => {
  const less = { ...SAM, shares: ["todos", "history"] as Seat["shares"], focus_seconds: undefined, app: undefined, site: undefined };
  openTheirDesk(less, { todo_list: PIECES.todo_list, history: PIECES.history });
  await screen.findByRole("region", { name: "Sam’s to-dos" });
  expect(pieceNames()).toEqual(["Sam’s to-dos", "Sam’s history"]);
  expect(screen.getByText("Sam shares status, to-dos and history")).toBeInTheDocument();
  expect(screen.queryByText(/on the phone ·/)).toBeNull();
  expect(screen.queryByText("Chrome")).toBeNull();
});

it("says Sam keeps the rest private when only the status shows", async () => {
  openTheirDesk({ ...SAM, shares: [], focus_seconds: undefined, todos: undefined, app: undefined, site: undefined, nudge: undefined }, {});
  expect(await screen.findByText("Sam keeps the rest private.")).toBeInTheDocument();
  expect(screen.getByText("Sam shares status only")).toBeInTheDocument();
  expect(pieceNames()).toEqual([]);
  expect(screen.queryByRole("button", { name: /Nudge/ })).toBeNull(); // nudges off
});

it("sends your own name to your desk, without asking the Pi", async () => {
  const sent = openTheirDesk(SAM, PIECES, "/people/dayan");
  await waitFor(() => expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent("/me"));
  expect(sent.map((request) => request.path)).not.toContain("/api/people/dayan");
});

it("says so for a name nobody has", async () => {
  openTheirDesk(SAM, PIECES, "/people/nobody");
  expect(await screen.findByText("Nobody here goes by that name.")).toBeInTheDocument();
});
