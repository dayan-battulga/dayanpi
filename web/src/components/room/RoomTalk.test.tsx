import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { toast } from "sonner";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import type { TalkKind } from "@/lib/talk";
import type { Seat } from "@/lib/types";
import { answer, serveApi } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { OWNER, makeFocus, makeSeat, makeSnapshot } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

// The room's voices without a mic or a socket: what the page asks of them, and who it's told is talking.
const voices = vi.hoisted(() => ({ supported: true as boolean | null, talking: {} as Record<string, string>, asked: [] as string[] }));
// Like the real hook, talkTo and stop stay the same functions from render to render.
vi.mock("@/hooks/useTalk", async () => {
  const { useCallback, useState } = await import("react");
  return {
    useTalk: () => {
      const [target, setTarget] = useState<string | null>(null);
      const talkTo = useCallback((next: string) => {
        voices.asked.push(`talk to ${next || "everyone"}`);
        setTarget(next);
      }, []);
      const stop = useCallback(() => {
        voices.asked.push("stop");
        setTarget(null);
      }, []);
      return { supported: voices.supported, target, talking: voices.talking, talkTo, stop };
    },
  };
});

const SAM = makeSeat({ username: "sam", name: "Sam", talk: true });
const ALEX = makeSeat({ username: "alex", name: "Alex" }); // keeps direct talk to themself

function openRoom(seats: Seat[] = [makeSeat(), SAM, ALEX], path = "/") {
  serveApi({ "GET /api/me": answer({ user: OWNER }), "GET /api/focus": answer({ segments: [] }), "GET /api/people/sam": answer({ ...SAM, here_since: null }) });
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  FakeEventSource.latest?.send({ ...makeSnapshot(makeFocus()), room: { seats } });
  return userEvent.setup();
}

const seatOf = (name: string) => screen.getByRole("article", { name: new RegExp(`^${name},`) });

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
  voices.supported = true;
  voices.talking = {};
  voices.asked = [];
});

afterEach(() => {
  vi.unstubAllGlobals();
  toast.dismiss();
});

it("turns your mic on for everyone and off again with the same button, and says so on your seat", async () => {
  const user = openRoom();
  const button = await screen.findByRole("button", { name: "Talk to everyone" });
  expect(screen.getByText("For one person, use their seat")).toBeInTheDocument();
  await user.click(button);
  expect(button).toHaveAccessibleName("Mic on · everyone");
  expect(button).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("Click to stop · Esc works too")).toBeInTheDocument();
  expect(within(seatOf("Dayan")).getByText("To everyone").closest(".talk-chip")).not.toBeNull();
  expect(seatOf("Dayan")).toHaveAttribute("data-talk", "on");
  await user.click(button);
  expect(voices.asked).toEqual(["talk to everyone", "stop"]);
  expect(seatOf("Dayan")).not.toHaveAttribute("data-talk");
});

it("stops with Esc, and when you leave the Room", async () => {
  const user = openRoom();
  await user.click(await screen.findByRole("button", { name: "Talk to everyone" }));
  await user.keyboard("{Escape}");
  expect(screen.getByRole("button", { name: "Talk to everyone" })).toHaveAttribute("aria-pressed", "false");
  await user.click(screen.getByRole("button", { name: "Talk to everyone" }));
  voices.asked = [];
  await user.click(screen.getByRole("link", { name: "Desk" }));
  await waitFor(() => expect(voices.asked).toContain("stop"));
});

it("talks to one person from the mic on their seat, rings their seat softly, and the main button stops it", async () => {
  const user = openRoom();
  const mic = within(await screen.findByRole("article", { name: /^Sam,/ })).getByRole("button", { name: "Talk to Sam" });
  expect(within(seatOf("Alex")).queryByRole("button", { name: /Talk to/ })).toBeNull(); // Alex doesn't take direct talk
  expect(within(seatOf("Dayan")).queryByRole("button", { name: /Talk to/ })).toBeNull(); // never to yourself
  await user.click(mic);
  expect(voices.asked).toEqual(["talk to sam"]);
  expect(within(seatOf("Sam")).getByRole("button", { name: "Talking to Sam" })).toHaveAttribute("aria-pressed", "true");
  expect(seatOf("Sam")).toHaveAttribute("data-talk", "soft");
  expect(within(seatOf("Dayan")).getByText("To Sam only")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Mic on · Sam only" }));
  expect(voices.asked).toEqual(["talk to sam", "stop"]);
});

it("has a Talk to Sam toggle in the quick peek, next to Nudge", async () => {
  const user = openRoom();
  await user.click(await screen.findByRole("button", { name: "Peek at Sam" }));
  const peek = await screen.findByRole("dialog", { name: "Sam" });
  await user.click(within(peek).getByRole("button", { name: "Talk to Sam" }));
  expect(within(peek).getByRole("button", { name: "Mic on · Sam only (stop)" })).toHaveAttribute("aria-pressed", "true");
  await user.click(within(peek).getByRole("button", { name: "Mic on · Sam only (stop)" }));
  expect(voices.asked).toEqual(["talk to sam", "stop"]);
});

it("stops talking to someone who leaves or turns direct talk off", async () => {
  const user = openRoom();
  await user.click(within(await screen.findByRole("article", { name: /^Sam,/ })).getByRole("button", { name: "Talk to Sam" }));
  FakeEventSource.latest?.send({ ...makeSnapshot(makeFocus()), room: { seats: [makeSeat(), { ...SAM, talk: undefined }, ALEX] } });
  await waitFor(() => expect(voices.asked).toEqual(["talk to sam", "stop"]));
});

it("shows who's talking on their seat: to everyone, or to you, with a ring", async () => {
  voices.talking = { sam: "you" satisfies TalkKind, alex: "everyone" satisfies TalkKind };
  openRoom();
  expect(within(await screen.findByRole("article", { name: /^Sam,/ })).getByText("To you").closest(".talk-chip")).not.toBeNull();
  expect(seatOf("Sam")).toHaveAttribute("data-talk", "on");
  expect(within(seatOf("Alex")).getByText("To everyone")).toBeInTheDocument();
  expect(seatOf("Dayan")).not.toHaveAttribute("data-talk");
});

it("says talking needs Chrome, with no talk buttons, when WebCodecs Opus isn't there", async () => {
  voices.supported = false;
  openRoom();
  expect(await screen.findByText("Talking needs Chrome")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Talk to/ })).toBeNull();
});
