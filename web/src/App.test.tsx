import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionConfig } from "motion/react";
import { MemoryRouter, useLocation } from "react-router";
import { toast } from "sonner";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import { showToast } from "@/components/ui/toaster";
import { ME_RETRY_MS } from "@/hooks/useMe";
import { PHONE_QUERY } from "@/hooks/useMediaQuery";
import { STREAM_RETRY_MS } from "@/hooks/useSnapshot";
import { loadPage } from "@/lib/navigation";
import type { User } from "@/lib/types";
import { answer, serveApi, type Route } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { MEMBER, OWNER, makeFocus, makeSnapshot } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

const realMatchMedia = window.matchMedia;

// The Pi's answers the pages ask for on load: who you are, and today's segments.
function servePi(me: User = OWNER, extra: Record<string, Route> = {}) {
  const start = Date.now() / 1000 - 3600;
  const sent = serveApi({
    "GET /api/me": answer({ user: me }),
    "GET /api/focus": answer({ segments: [{ state: "working", start, end: null }] }),
    ...extra,
  });
  return sent;
}

function ShowPath() {
  return <output aria-label="Path">{useLocation().pathname}</output>;
}

function renderApp(path = "/me") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <ShowPath />
    </MemoryRouter>,
  );
}

// /pi is a lazy page, and it waits for /api/me to say you're the owner.
async function openPi() {
  renderApp("/pi");
  const cameras = await screen.findByRole("region", { name: "Cameras" });
  return cameras;
}

// The stats' plain copies (the rolling digits are hidden from screen readers): name and value.
function readPiStats() {
  const stats = Array.from(document.querySelectorAll(".pi-stat"), (stat) => [stat.querySelector("dt")?.textContent, stat.querySelector("dd .sr-only")?.textContent]);
  return stats;
}

const feedSources = () => Array.from(document.querySelectorAll(".cameras img"), (image) => image.getAttribute("src"));

// A phone-sized window: only the phone query matches.
function usePhone() {
  window.matchMedia = (query: string) => ({ ...realMatchMedia(query), matches: query === PHONE_QUERY });
}

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
  servePi();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.mocked(loadPage).mockClear();
  window.localStorage.clear();
  window.matchMedia = realMatchMedia;
  document.documentElement.dataset.theme = "light";
  // Sonner hands every toast that was never dismissed to the next Toaster that mounts, so the next test's page.
  toast.dismiss();
});

it("draws today's cards on /me from one stream", async () => {
  renderApp();
  expect(FakeEventSource.latest?.url).toBe("/api/stream");

  FakeEventSource.latest?.send(makeSnapshot());

  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Focused");
  expect(screen.getByRole("timer")).toHaveAccessibleName("02:05");
  expect(document.querySelector("#focus-stats .sr-only")).toHaveTextContent("1h 05m focused, 5m on your phone, 3 pickups");
  expect(screen.getByText("finish the report")).toBeInTheDocument();
  expect(screen.getByText("12m")).toBeInTheDocument();
  expect(document.getElementById("mac-line")).toHaveTextContent("On the Mac ·Code");
  expect(screen.queryByRole("region", { name: "Cameras" })).toBeNull();
  expect(document.querySelector(".pi-stats")).toBeNull();

  await waitFor(() => expect(document.querySelector(".segment.is-working.is-live")).not.toBeNull());
  expect(screen.queryByText("Sat down to work")).toBeNull(); // the Today list is gone: the timeline shows the same
});

it("puts the cameras, hidden, and the Pi's numbers on /pi", async () => {
  const cameras = await openPi();
  FakeEventSource.latest?.send(makeSnapshot());

  expect(within(cameras).getByRole("heading", { level: 1 })).toHaveTextContent("Cameras");
  expect(within(cameras).getByText("Hidden while you work")).toBeVisible();
  expect(within(cameras).getByRole("button", { name: "Peek" })).toHaveAttribute("aria-pressed", "false");
  expect(cameras.querySelectorAll("figure")).toHaveLength(1); // no side camera
  expect(feedSources()).toEqual([expect.stringMatching(/^data:/)]); // nothing opened while hidden
  expect(cameras.querySelector(".cam-note")).toHaveTextContent("The readings keep updating while the picture is hidden.");
  expect(readPiStats()).toEqual([
    ["Temperature", "48°C"],
    ["CPU", "23%"],
    ["Memory of 8 GB", "2.9 GB"],
    ["Up for", "3d 1h"],
  ]);
  expect(document.querySelectorAll(".pi-value number-flow-react")).toHaveLength(5); // they roll
  expect(document.querySelector(".pi-foot")).toHaveTextContent("YOLO26n · one check a second · one camera");
  expect(screen.queryByRole("alert")).toBeNull();
});

it("turns the temperature bar warm, then hot", async () => {
  await openPi();
  const tones = [] as (string | null | undefined)[];
  for (const temperature_celsius of [48.2, 72, 83]) {
    FakeEventSource.latest?.send({ ...makeSnapshot(), temperature_celsius });
    tones.push(document.querySelector(".pi-bar [data-tone]")?.getAttribute("data-tone"));
  }
  expect(tones).toEqual(["nominal", "elevated", "critical"]);
});

it("warns about undervoltage on the Pi page while it's happening", async () => {
  await openPi();
  const snapshot = makeSnapshot();
  FakeEventSource.latest?.send({ ...snapshot, throttle: { ...snapshot.throttle, is_undervoltage: true } });
  expect(screen.getByRole("alert")).toHaveTextContent("Undervoltage");
  expect(screen.getByRole("alert")).toHaveClass("pi-alert");
  FakeEventSource.latest?.send(snapshot);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("sends / to /me until the room exists", async () => {
  renderApp("/");
  await waitFor(() => expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent("/me"));
  expect(screen.getByRole("link", { name: "Desk" })).toHaveAttribute("aria-current", "page");
});

it.each([
  ["/me", "Desk"],
  ["/pi", "Pi"],
] as const)("marks the tab for %s as the current page", async (path, tab) => {
  renderApp(path);
  const tabs = within(screen.getByRole("navigation", { name: "Pages" }));
  expect(await tabs.findByRole("link", { name: tab })).toHaveAttribute("aria-current", "page");
  expect(tabs.getAllByRole("link").filter((link) => link.getAttribute("aria-current") === "page")).toHaveLength(1);
});

it("moves the pill and the page when you pick a tab", async () => {
  const user = userEvent.setup();
  renderApp();
  await user.click(await screen.findByRole("link", { name: "Pi" }));
  expect(await screen.findByRole("region", { name: "Cameras" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Pi" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("link", { name: "Desk" })).not.toHaveAttribute("aria-current");
  expect(document.querySelectorAll(".tab-pill")).toHaveLength(1);
  expect(screen.getByRole("link", { name: "Pi" }).querySelector(".tab-pill")).not.toBeNull();
});

it("marks no tab on Settings, and rings the account button instead", async () => {
  renderApp("/settings");
  const account = await screen.findByRole("button", { name: "Account: Dayan" });
  expect(account).toHaveAttribute("aria-current", "page");
  expect(within(screen.getByRole("navigation", { name: "Pages" })).getAllByRole("link").some((link) => link.hasAttribute("aria-current"))).toBe(false);
});

it("shows a member the desk without the owner's controls, and no Pi tab", async () => {
  servePi(MEMBER);
  renderApp();
  FakeEventSource.latest?.send({ focus: makeFocus({ camera_access: "owner_only" }) });

  expect(await screen.findByRole("button", { name: "Account: Sam" })).toBeInTheDocument();
  expect(screen.getByText("finish the report")).toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: "New to-do" })).toBeNull();
  expect(screen.queryByRole("checkbox", { name: "Done: finish the report" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Pause Mac tracking" })).toBeNull();
  expect(document.getElementById("mac-line")).toHaveTextContent("On the Mac ·Code");
  expect(screen.getByRole("link", { name: "Desk" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Pi" })).toBeNull();
});

it("sends a member who types /pi to their desk", async () => {
  servePi(MEMBER);
  renderApp("/pi");
  await waitFor(() => expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent("/me"));
  expect(screen.queryByRole("region", { name: "Cameras" })).toBeNull();
});

it("puts the pages in a dock on a phone, with a + that jumps to a new to-do", async () => {
  usePhone();
  const user = userEvent.setup();
  renderApp("/settings");
  const dock = within(screen.getByRole("navigation", { name: "Pages" }));
  expect(dock.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
  expect(document.querySelector(".tabs")).toBeNull();
  expect(screen.queryByRole("button", { name: "Search and commands" })).toBeNull(); // RoomPhone has no ⌘K

  await user.click(await dock.findByRole("button", { name: "New to-do" }));

  expect(await screen.findByRole("textbox", { name: "New to-do" })).toHaveFocus();
  expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent("/me");
  expect(dock.getByRole("link", { name: "Desk" })).toHaveAttribute("aria-current", "page");
});

it("focuses the new to-do box right away from the dock on the desk", async () => {
  usePhone();
  const user = userEvent.setup();
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot());
  await user.click(await screen.findByRole("button", { name: "New to-do" }));
  expect(screen.getByRole("textbox", { name: "New to-do" })).toHaveFocus();
});

it("has no + in a member's dock: they can't add to the owner's list", async () => {
  usePhone();
  servePi(MEMBER);
  renderApp();
  await screen.findByRole("button", { name: "Account: Sam" });
  expect(screen.queryByRole("button", { name: "New to-do" })).toBeNull();
});

// Every toast Sonner has on screen or waiting, newest first.
function readToasts() {
  const toasts = Array.from(document.querySelectorAll("[data-sonner-toast]"), (toast) => ({ text: toast.textContent, visible: toast.getAttribute("data-visible") === "true" }));
  return toasts;
}

it("puts each hand sign in a toast once, though every snapshot repeats it", async () => {
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ gesture: { name: "wave", age_s: 0.6 } })));
  expect(await screen.findByText("wave")).toBeInTheDocument();

  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ gesture: { name: "wave", age_s: 1.6 } })));
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ gesture: { name: "wave", age_s: 0.3 } }))); // made again

  await waitFor(() => expect(readToasts()).toHaveLength(2));
});

it("has no toast for a hand sign that's already old when the page opens", async () => {
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ gesture: { name: "wave", age_s: 30 } })));
  await screen.findByRole("button", { name: "Account: Dayan" });
  expect(readToasts()).toEqual([]);
});

const SAYING = "3 things left, almost 5 hours before bed. You've got this.";
const VOICE_ON = { enabled: true, backend: "piper", problem: null };

// A peace sign that fired age_s ago, with what it's saying; the toast never shows for it.
function sendPeace(age_s: number, speaking: boolean, voice = VOICE_ON) {
  const at = 1_794_877_938; // the same message in every snapshot
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ voice, gesture: { name: "peace", age_s }, spoken: { text: SAYING, at, age_s, speaking } })));
}

it("shows what the peace sign says in the pill while the voice says it, then lets it go", async () => {
  renderApp();
  sendPeace(0.4, true);
  const pill = (await screen.findByText(SAYING)).closest(".peace-pill");
  expect(pill?.closest('[role="status"]')).toHaveClass("peace"); // read out as it comes in
  sendPeace(9, true); // a long message: still talking past 6 s
  expect(screen.getByText(SAYING)).toBeInTheDocument();
  sendPeace(10, false);
  await waitFor(() => expect(screen.queryByText(SAYING)).toBeNull());
  sendPeace(11, false);
  expect(screen.queryByText(SAYING)).toBeNull();
  expect(readToasts()).toEqual([]);
});

it("keeps the pill 6 s with the voice off, and none for an old message on load", async () => {
  const voiceOff = { enabled: false, backend: "off", problem: null };
  renderApp();
  sendPeace(30, false, voiceOff);
  await screen.findByRole("button", { name: "Account: Dayan" });
  expect(screen.queryByText(SAYING)).toBeNull();
  sendPeace(0.5, false, voiceOff);
  expect(await screen.findByText(SAYING)).toBeInTheDocument();
  sendPeace(5.5, false, voiceOff);
  expect(screen.getByText(SAYING)).toBeInTheDocument();
  sendPeace(6.5, false, voiceOff);
  await waitFor(() => expect(screen.queryByText(SAYING)).toBeNull());
});

it("only fades the pill in with reduced motion", async () => {
  const pillStyle = async () => ((await screen.findByText(SAYING)).closest(".peace-pill") as HTMLElement).style;
  const { unmount } = render(
    <MemoryRouter initialEntries={["/me"]}>
      <App />
    </MemoryRouter>,
  );
  sendPeace(0.4, true);
  expect((await pillStyle()).filter).toBe("blur(4px)"); // where the rise starts
  unmount();
  render(
    <MotionConfig reducedMotion="always">
      <MemoryRouter initialEntries={["/me"]}>
        <App />
      </MemoryRouter>
    </MotionConfig>,
  );
  sendPeace(0.4, true);
  const reduced = await pillStyle();
  expect([reduced.opacity, reduced.filter, reduced.transform]).toEqual(["0", "", ""]);
});

it("shows one toast at a time, the newest", async () => {
  renderApp();
  act(() => {
    showToast("Nudged Sam");
    showToast("Nudged Alex");
  });
  await screen.findByText("Nudged Alex");
  expect(readToasts()).toEqual([
    { text: "Nudged Alex", visible: true },
    { text: "Nudged Sam", visible: false },
  ]);
});

it("drops the boxes once the overlay is more than 3 s old", async () => {
  await openPi();
  FakeEventSource.latest?.send(makeSnapshot());
  expect(document.querySelectorAll(".box:not(.is-leaving)")).toHaveLength(1);

  const stale = makeFocus();
  FakeEventSource.latest?.send(makeSnapshot({ ...stale, overlay: stale.overlay && { ...stale.overlay, age_s: 3.5 } }));

  expect(document.querySelectorAll(".box:not(.is-leaving)")).toHaveLength(0);
});

it("shows both cameras side by side; Peek opens both feeds with the readings, Hide closes them", async () => {
  const user = userEvent.setup();
  const cameras = await openPi();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ side_camera: true })));
  expect(Array.from(cameras.querySelectorAll("figcaption"), (caption) => caption.textContent)).toEqual(["Front", "Side"]);
  expect(within(cameras).getByText("Hidden")).toBeVisible();

  await user.click(within(cameras).getByRole("button", { name: "Peek" }));
  expect(feedSources()).toEqual([expect.stringMatching(/^\/video\?t=/), expect.stringMatching(/^\/video\/side\?t=/)]);
  expect(within(cameras).getByRole("button", { name: "Hide" })).toHaveAttribute("aria-pressed", "true");
  expect(cameras.querySelectorAll(".cam-tile[data-peeking]")).toHaveLength(2);
  expect(document.querySelector(".box.is-person .box-label")).toHaveTextContent("person 0.92");
  expect(cameras.querySelector(".cam-note")).toHaveTextContent("person 0.92 · no phone");
  expect(window.localStorage.getItem("dayanpi.peek")).toBe("1");

  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ side_camera: true, last_check: { person: 0.9, phone: 0.81, elapsed_ms: 190 } })));
  expect(cameras.querySelector(".cam-note")).toHaveTextContent("person 0.90 · phone in hand 0.81");

  await user.click(within(cameras).getByRole("button", { name: "Hide" }));
  expect(feedSources()).toEqual([expect.stringMatching(/^data:/), expect.stringMatching(/^data:/)]);
  expect(cameras.querySelectorAll(".cam-tile[data-peeking]")).toHaveLength(0);
});

it.each(["tailscale_only", "owner_only"] as const)("locks the cameras and never opens /video when the camera is %s", async (access) => {
  window.localStorage.setItem("dayanpi.peek", "1");
  const cameras = await openPi();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_access: access, side_camera: true, overlay: null })));
  expect(within(cameras).getByText("Only on your own devices")).toBeVisible();
  expect(within(cameras).getByText("Locked")).toBeVisible();
  expect(cameras.querySelector(".cam-note")).toHaveTextContent("This browser isn’t one of your Tailscale devices, so the cameras stay closed.");
  expect(cameras.querySelector("img")).toBeNull();
  expect(cameras.querySelector(".cam-tile[data-peeking]")).toBeNull();
  expect(within(cameras).queryByRole("button", { name: /Peek|Hide/ })).toBeNull();
});

it("opens the feed as before when the camera is open, or the Pi doesn't say", async () => {
  window.localStorage.setItem("dayanpi.peek", "1");
  await openPi();
  expect(feedSources()).toEqual([]); // nothing until the first status says whether /video will answer
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_access: "open" })));
  expect(feedSources()).toEqual([expect.stringMatching(/^\/video\?t=/)]);
  FakeEventSource.latest?.send(makeSnapshot(makeFocus()));
  expect(feedSources()).toEqual([expect.stringMatching(/^\/video\?t=/)]);
});

it("shows Reconnecting next to the wordmark and dims the live page while the stream is down", async () => {
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot());
  expect(screen.queryByText("Reconnecting")).toBeNull();

  FakeEventSource.latest?.fail();

  expect(within(document.querySelector(".brand") as HTMLElement).getByRole("status")).toHaveTextContent("Reconnecting");
  expect(document.querySelector(".frame")).toHaveAttribute("data-connection", "reconnecting");
  expect(document.querySelector(".frame[data-connection=reconnecting] .live")).not.toBeNull();

  FakeEventSource.latest?.send(makeSnapshot());
  expect(screen.queryByText("Reconnecting")).toBeNull();
  expect(document.querySelector(".frame")).toHaveAttribute("data-connection", "connected");
});

it("asks /api/me when the stream drops, and goes to /login on a 401", async () => {
  renderApp();
  await screen.findByRole("button", { name: "Account: Dayan" });
  servePi(OWNER, { "GET /api/me": answer({ detail: "sign in first" }, 401) });
  window.history.pushState({}, "", "/?x=1");

  FakeEventSource.latest?.fail();

  expect(screen.getByText("Reconnecting")).toBeInTheDocument();
  await waitFor(() => expect(loadPage).toHaveBeenCalledWith("/login?next=%2F%3Fx%3D1"));
});

it("asks /api/me again when it got no answer, so the owner isn't stuck read-only", async () => {
  vi.useFakeTimers();
  servePi(OWNER, { "GET /api/me": answer({ detail: "Pi restarting" }, 503) });
  renderApp();
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(screen.queryByRole("button", { name: "Account: Dayan" })).not.toBeInTheDocument();

  servePi();
  await act(() => vi.advanceTimersByTimeAsync(ME_RETRY_MS));

  expect(screen.getByRole("button", { name: "Account: Dayan" })).toBeInTheDocument();
});

it("reopens the stream a few seconds after the Pi turns it away with a 502 or 503", async () => {
  renderApp();
  await screen.findByRole("button", { name: "Account: Dayan" });
  const first = FakeEventSource.latest;
  vi.useFakeTimers();

  first?.fail(FakeEventSource.CLOSED);

  expect(screen.getByText("Reconnecting")).toBeInTheDocument();
  expect(first?.closed).toBe(true);
  act(() => vi.advanceTimersByTime(STREAM_RETRY_MS));
  expect(FakeEventSource.latest).not.toBe(first);
  FakeEventSource.latest?.send(makeSnapshot());
  expect(screen.queryByText("Reconnecting")).toBeNull();
});

// The desk once /api/me said who you are (the palette's list depends on it).
async function openDesk(me: User = OWNER) {
  servePi(me);
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot());
  await screen.findByRole("button", { name: `Account: ${me.display_name}` });
}

function readCommands(dialog: HTMLElement) {
  const labels = within(dialog)
    .getAllByRole("option")
    .map((option) => option.querySelector(".palette-label")?.textContent);
  return labels;
}

it.each(["{Meta>}k{/Meta}", "{Control>}k{/Control}"])("opens ⌘K with %s, filters as you type, and closes on Esc", async (keys) => {
  const user = userEvent.setup();
  await openDesk();

  await user.keyboard(keys);

  const dialog = await screen.findByRole("dialog", { name: "Commands" });
  const search = within(dialog).getByRole("combobox", { name: "Command" });
  expect(search).toHaveFocus();
  expect(readCommands(dialog)).toEqual(["Add a to-do", "Go to Desk", "Go to Pi", "Go to Settings", "Switch theme", "Pause Mac tracking"]);
  const first = within(dialog).getByRole("option", { selected: true });
  expect(first.querySelector(".palette-label")).toHaveTextContent("Add a to-do");
  expect(first.querySelector(".palette-key")).toHaveTextContent("N");
  expect(dialog.querySelectorAll(".palette-highlight")).toHaveLength(1);
  expect(first.querySelector(".palette-highlight")).not.toBeNull();

  await user.type(search, "theme");
  expect(readCommands(dialog)).toEqual(["Switch theme"]);

  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("runs the highlighted command on Enter and closes", async () => {
  const user = userEvent.setup();
  await openDesk();
  await user.click(screen.getByRole("button", { name: "Search and commands" }));

  await user.type(await screen.findByRole("combobox", { name: "Command" }), "go to pi");
  await user.keyboard("{Enter}");

  await waitFor(() => expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent("/pi"));
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("gives a member only the commands that are theirs", async () => {
  const user = userEvent.setup();
  await openDesk(MEMBER);
  await user.keyboard("{Control>}k{/Control}");
  expect(readCommands(await screen.findByRole("dialog", { name: "Commands" }))).toEqual(["Go to Desk", "Go to Settings", "Switch theme"]);
});

it("pauses Mac tracking from ⌘K, and the Mac line follows", async () => {
  const user = userEvent.setup();
  const sent = servePi(OWNER, { "POST /api/mac/tracking": answer({ enabled: false }) });
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ mac_tracking: true })));
  await screen.findByRole("button", { name: "Account: Dayan" });

  await user.keyboard("{Control>}k{/Control}");
  await user.click(await screen.findByRole("option", { name: "Pause Mac tracking" }));

  await waitFor(() => expect(sent.filter((request) => request.path === "/api/mac/tracking").map((request) => request.body)).toEqual([{ enabled: false }]));
  expect(await screen.findByRole("button", { name: "Resume Mac tracking" })).toBeInTheDocument();
  expect(document.getElementById("mac-line")).toHaveTextContent("Mac tracking paused");
  await user.keyboard("{Control>}k{/Control}");
  expect(await screen.findByRole("option", { name: "Resume Mac tracking" })).toBeInTheDocument();
});

it("ignores single-key shortcuts while you're typing in a field", async () => {
  const user = userEvent.setup();
  await openDesk();
  const box = screen.getByRole("textbox", { name: "New to-do" });

  await user.type(box, "ntgp");

  expect(box).toHaveValue("ntgp");
  expect(document.documentElement.dataset.theme).not.toBe("dark");
  expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent("/me");
});

it("jumps to a new to-do with N from another page, typing nothing into it", async () => {
  const user = userEvent.setup();
  renderApp("/settings");
  await screen.findByRole("textbox", { name: "Display name" });

  await user.keyboard("n");

  const box = await screen.findByRole("textbox", { name: "New to-do" });
  await waitFor(() => expect(box).toHaveFocus());
  expect(box).toHaveValue("");
});

it("goes to a page with G then a letter, and flips the theme with T", async () => {
  const user = userEvent.setup();
  await openDesk();

  await user.keyboard("gp");
  await waitFor(() => expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent("/pi"));
  await user.keyboard("t");

  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(screen.getByRole("button", { name: "Switch to light mode" })).toBeInTheDocument();
});
