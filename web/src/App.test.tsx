import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  const camera = await screen.findByRole("region", { name: "Camera" });
  return camera;
}

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
  expect(document.getElementById("focus-state")).toHaveTextContent("Working");
  expect(document.getElementById("focus-timer")).toHaveTextContent("2:05");
  expect(document.getElementById("focus-working")).toHaveTextContent("1h 05m");
  expect(document.getElementById("focus-pickups")).toHaveTextContent("3");
  expect(screen.getByText("finish the report")).toBeInTheDocument();
  expect(screen.getByText("12m")).toBeInTheDocument();
  expect(document.getElementById("mac")).toHaveTextContent(/^Code$/);
  expect(screen.queryByRole("region", { name: "Camera" })).toBeNull();
  expect(document.getElementById("pi")).toBeNull();

  await waitFor(() => expect(document.querySelector(".segment.is-working.is-live")).not.toBeNull());
  expect(screen.getByText("Sat down to work")).toBeInTheDocument();
});

it("puts the camera and the Pi's numbers on /pi", async () => {
  const camera = await openPi();
  FakeEventSource.latest?.send(makeSnapshot());

  expect(camera.querySelector(".reading[data-key=person] .reading-value")).toHaveTextContent("0.92");
  expect(document.getElementById("check-ms")).toHaveTextContent("~186 ms each");
  expect(document.querySelector(".box.is-person .box-label")).toHaveTextContent("person 0.92");
  expect(document.getElementById("pi-summary")).toHaveTextContent("Running smooth");
  expect(document.getElementById("temp")).toHaveTextContent("48.2");
  expect(document.getElementById("cpu-cores")?.children).toHaveLength(4);
  expect(document.getElementById("net")).toHaveTextContent("↓ 120 kb/s · ↑ 1.5 Mb/s");
  expect(screen.queryByRole("region", { name: "On the Mac" })).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("warns about undervoltage on the Pi page", async () => {
  await openPi();
  const snapshot = makeSnapshot();
  FakeEventSource.latest?.send({ ...snapshot, throttle: { ...snapshot.throttle, is_undervoltage: true } });
  expect(screen.getByRole("alert")).toHaveTextContent("Undervoltage");
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
  expect(await screen.findByRole("region", { name: "Camera" })).toBeInTheDocument();
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
  expect(screen.queryByRole("switch", { name: "Mac tracking" })).toBeNull();
  expect(document.getElementById("mac")).toHaveTextContent(/^Code$/);
  expect(screen.getByRole("link", { name: "Desk" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Pi" })).toBeNull();
});

it("sends a member who types /pi to their desk", async () => {
  servePi(MEMBER);
  renderApp("/pi");
  await waitFor(() => expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent("/me"));
  expect(screen.queryByRole("region", { name: "Camera" })).toBeNull();
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
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ gesture: { name: "peace", age_s: 0.6 } })));
  expect(await screen.findByText("✌️ Peace sign: reading your to-dos")).toBeInTheDocument();

  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ gesture: { name: "peace", age_s: 1.6 } })));
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ gesture: { name: "peace", age_s: 0.3 } }))); // made again

  await waitFor(() => expect(readToasts()).toHaveLength(2));
});

it("has no toast for a hand sign that's already old when the page opens", async () => {
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ gesture: { name: "peace", age_s: 30 } })));
  await screen.findByRole("button", { name: "Account: Dayan" });
  expect(readToasts()).toEqual([]);
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

it("shows the flip button only with a side camera, and only one feed at a time", async () => {
  await openPi();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ side_camera: true })));
  const flip = screen.getByRole("button", { name: "Show the side camera" });
  const [front, side] = Array.from(document.querySelectorAll(".feed-frame"));
  expect(front).toBeVisible();
  expect(side).not.toBeVisible();

  act(() => flip.click());

  expect(front).not.toBeVisible();
  expect(side).toBeVisible();
  expect(screen.getByRole("button", { name: "Show the front camera" })).toBeInTheDocument();
});

it("puts what's in front on the Mac at the top, the site big when it's a browser", () => {
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ app: "Google Chrome", site: "youtube.com" })));
  const card = screen.getByRole("region", { name: "On the Mac" });
  expect(document.getElementById("mac")).toHaveTextContent(/^youtube\.com$/);
  expect(card).toHaveTextContent("in Google Chrome");
  expect(card.compareDocumentPosition(document.getElementById("focus-card")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ app: null })));
  expect(document.getElementById("mac")).toHaveTextContent("Not reporting");
});

it("pauses the Mac tracker from its switch, flipping right away", async () => {
  const user = userEvent.setup();
  const sent = servePi(OWNER, { "POST /api/mac/tracking": answer({ enabled: false }) });
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ mac_tracking: true })));
  const toggle = await screen.findByRole("switch", { name: "Mac tracking" });
  expect(toggle).toHaveAttribute("aria-checked", "true");

  await user.click(toggle);

  expect(sent.filter((request) => request.path === "/api/mac/tracking").map((request) => request.body)).toEqual([{ enabled: false }]);
  expect(screen.getByRole("switch", { name: "Mac tracking" })).toHaveAttribute("aria-checked", "false");
  expect(document.getElementById("mac")).toHaveTextContent("Paused");
});

it("puts the switch back when the Pi doesn't take it", async () => {
  const user = userEvent.setup();
  servePi(OWNER, {
    "POST /api/mac/tracking": () => {
      throw new TypeError("Failed to fetch");
    },
  });
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ mac_tracking: true })));
  await user.click(await screen.findByRole("switch", { name: "Mac tracking" }));
  await waitFor(() => expect(screen.getByRole("switch", { name: "Mac tracking" })).toHaveAttribute("aria-checked", "true"));
  expect(document.getElementById("mac")).toHaveTextContent(/^Code$/);
  expect(await screen.findByText("Couldn't pause Mac tracking")).toBeInTheDocument();
});

it("says Paused when the Pi says the switch is off", async () => {
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ mac_tracking: false })));
  expect(await screen.findByRole("switch", { name: "Mac tracking" })).toHaveAttribute("aria-checked", "false");
  expect(document.getElementById("mac")).toHaveTextContent("Paused");
});

it.each([
  ["tailscale_only", "Tailscale only", "Open the dashboard on one of your own Tailscale devices to see the camera."],
  ["owner_only", "The camera is private", "The readings next to it still update."],
] as const)("never opens /video when the camera is %s, and says why", async (access, title, text) => {
  window.localStorage.setItem("dayanpi.peek", "1");
  const camera = await openPi();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_access: access, side_camera: true, overlay: null })));
  expect(camera.querySelector(".veil")).toHaveTextContent(title);
  expect(camera.querySelector(".veil")).toHaveTextContent(text);
  expect(camera.querySelector("img")).toBeNull();
  expect(camera).not.toHaveClass("is-peeking");
  expect(document.getElementById("peek-toggle")).not.toBeVisible();
  expect(document.getElementById("camera-flip")).not.toBeVisible();
});

it("opens the feed as before when the camera is open, or the Pi doesn't say", async () => {
  window.localStorage.setItem("dayanpi.peek", "1");
  await openPi();
  expect(document.querySelector("#camera img")?.getAttribute("src")).toMatch(/^data:/); // nothing opened before the first status
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_access: "open" })));
  expect(document.querySelector("#camera img")?.getAttribute("src")).toMatch(/^\/video\?t=/);
  FakeEventSource.latest?.send(makeSnapshot(makeFocus()));
  expect(document.querySelector("#camera img")?.getAttribute("src")).toMatch(/^\/video\?t=/);
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

it("pauses Mac tracking from ⌘K, and the card's switch follows", async () => {
  const user = userEvent.setup();
  const sent = servePi(OWNER, { "POST /api/mac/tracking": answer({ enabled: false }) });
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ mac_tracking: true })));
  await screen.findByRole("button", { name: "Account: Dayan" });

  await user.keyboard("{Control>}k{/Control}");
  await user.click(await screen.findByRole("option", { name: "Pause Mac tracking" }));

  await waitFor(() => expect(sent.filter((request) => request.path === "/api/mac/tracking").map((request) => request.body)).toEqual([{ enabled: false }]));
  expect(await screen.findByRole("switch", { name: "Mac tracking" })).toHaveAttribute("aria-checked", "false");
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
