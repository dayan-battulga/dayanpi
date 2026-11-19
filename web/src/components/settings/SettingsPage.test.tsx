import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import { loadPage } from "@/lib/navigation";
import type { Account, User } from "@/lib/types";
import { answer, serveApi, type Route } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { MEMBER, OWNER, makeFocus, makeSeat, makeSnapshot } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

const DAY = 86400;
const MADE = 1_763_250_000;
const TOKEN = { id: 7, name: "MacBook", created_at: MADE, last_used_at: null };
const INVITE = { id: 3, created_at: MADE, expires_at: MADE + 7 * DAY };
const SAM: Account = { ...MEMBER, created_at: MADE };

function serveSettings(me: User, accounts: Account[] = [{ ...OWNER, created_at: MADE }, SAM], extra: Record<string, Route> = {}) {
  const sent = serveApi({
    "GET /api/me": answer({ user: me }),
    "GET /api/tokens": answer({ tokens: [TOKEN] }),
    "GET /api/invites": answer({ invites: [INVITE] }),
    "GET /api/accounts": answer({ accounts }),
    ...extra,
  });
  return sent;
}

// Settings lives inside the frame, which opens the stream and shares who you are with the page.
function renderSettings() {
  vi.stubGlobal("EventSource", FakeEventSource);
  render(
    <MemoryRouter initialEntries={["/settings"]}>
      <App />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  return user;
}

// Picks a section from the list on the left; the section is a region named by its heading.
async function openSection(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(await screen.findByRole("button", { name }));
  const section = within(await screen.findByRole("region", { name }));
  return section;
}

// One of Settings → Camera's picks, by its legend.
const choicesFor = (section: ReturnType<typeof within>, legend: string) => within(section.getByRole("group", { name: legend }));

const sectionNames = () => within(screen.getByRole("navigation", { name: "Settings sections" })).getAllByRole("listitem").map((item) => item.textContent);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(loadPage).mockClear();
});

it("starts on Profile, and the list picks a section, marked, rising in fresh", async () => {
  serveSettings(OWNER);
  const user = renderSettings();
  expect(await screen.findByRole("region", { name: "Profile" })).toBeInTheDocument();
  expect(sectionNames()).toEqual(["Profile", "Sharing", "Camera", "Voice and bedtime", "Mac helper", "Room and invites"]);
  expect(screen.getByRole("button", { name: "Profile" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByLabelText("Name")).toHaveValue("Dayan");
  const before = document.querySelector(".settings-section");

  await openSection(user, "Mac helper");

  expect(screen.queryByRole("region", { name: "Profile" })).toBeNull();
  expect(screen.getByRole("button", { name: "Mac helper" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("button", { name: "Profile" })).not.toHaveAttribute("aria-current");
  const after = document.querySelector(".settings-section");
  expect(after).not.toBe(before); // a new element, so its rise plays again
  expect(after).toHaveClass("rise");
});

it("shows the owner the invites and the accounts", async () => {
  serveSettings(OWNER);
  const user = renderSettings();
  const room = await openSection(user, "Room and invites");
  expect(await room.findByText("Sam")).toBeInTheDocument();
  expect(room.getByText("2 of 4 seats")).toBeInTheDocument();
  expect(within(room.getByRole("list", { name: "Open invites" })).getAllByRole("listitem")).toHaveLength(1);
});

it("shows a member only their own things, and never asks for the owner's lists", async () => {
  const sent = serveSettings(MEMBER);
  const user = renderSettings();
  await screen.findByRole("region", { name: "Profile" });
  expect(sectionNames()).toEqual(["Profile", "Sharing", "Camera", "Voice and bedtime", "Mac helper"]);
  const mac = await openSection(user, "Mac helper");
  expect(await mac.findByText("MacBook")).toBeInTheDocument();
  expect(mac.getByRole("switch", { name: "Track apps and sites" })).toBeInTheDocument(); // their own desk's
  expect(sent.map((request) => request.path)).not.toContain("/api/invites");
  expect(sent.map((request) => request.path)).not.toContain("/api/accounts");
});

it("flips Mac tracking from its switch, with the same POST as the Mac line", async () => {
  const sent = serveSettings(OWNER, undefined, { "POST /api/mac/tracking": answer({ enabled: false }) });
  const user = renderSettings();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ mac_tracking: true })));
  const mac = await openSection(user, "Mac helper");
  const toggle = mac.getByRole("switch", { name: "Track apps and sites" });
  expect(toggle).toHaveAttribute("aria-checked", "true");

  await user.click(toggle);

  expect(toggle).toHaveAttribute("aria-checked", "false");
  await waitFor(() => expect(sent.filter((request) => request.path === "/api/mac/tracking").map((request) => [request.method, request.body])).toEqual([["POST", { enabled: false }]]));
});

it("lets the owner switch the desk from the Pi's cameras to this browser's", async () => {
  const sent = serveSettings(OWNER, undefined, { "POST /api/track/source": answer({ source: "browser" }) });
  const user = renderSettings();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_source: "pi" })));
  const camera = await openSection(user, "Camera");
  const tracking = choicesFor(camera, "Track focus with");
  expect(tracking.getByRole("radio", { name: "This desk’s Pi cameras" })).toBeChecked();

  await user.click(tracking.getByRole("radio", { name: "This browser’s camera" }));

  expect(tracking.getByRole("radio", { name: "This browser’s camera" })).toBeChecked();
  expect(camera.getByText("Camera off")).toBeInTheDocument();
  expect(camera.getByRole("button", { name: "Turn on camera" })).toBeInTheDocument();
  expect(camera.queryByRole("link", { name: /tracker/ })).toBeNull();
  await waitFor(() => expect(sent.filter((request) => request.path === "/api/track/source").map((request) => [request.method, request.body])).toEqual([["POST", { source: "browser" }]]));
});

it("never lets a member pick the Pi's cameras", async () => {
  const sent = serveSettings(MEMBER);
  const user = renderSettings();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_source: "browser" })));
  const camera = await openSection(user, "Camera");
  const pi = camera.getByRole("radio", { name: "This desk’s Pi cameras" });
  expect(pi).toBeDisabled();
  expect(camera.getByRole("radio", { name: "This browser’s camera" })).toBeChecked();
  expect(camera.queryByRole("group", { name: "Room picture from" })).toBeNull(); // a member's picture is always their browser's
  await user.click(pi);
  expect(sent.map((request) => request.path)).not.toContain("/api/track/source");
});

it("gives the owner a room picture choice that starts where the desk is tracked, and turns on this camera for it", async () => {
  const sent = serveSettings(OWNER, undefined, { "POST /api/track/source": answer({ source: "pi", picture: "browser" }) });
  const user = renderSettings();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_source: "pi", picture_source: "pi" })));
  const camera = await openSection(user, "Camera");
  const picture = choicesFor(camera, "Room picture from");
  expect(picture.getByRole("radio", { name: "The Pi’s camera" })).toBeChecked();
  expect(camera.queryByRole("button", { name: "Turn on camera" })).toBeNull();

  await user.click(picture.getByRole("radio", { name: "This browser’s camera" }));

  expect(picture.getByRole("radio", { name: "This browser’s camera" })).toBeChecked();
  expect(choicesFor(camera, "Track focus with").getByRole("radio", { name: "This desk’s Pi cameras" })).toBeChecked(); // separate picks
  expect(camera.getByRole("button", { name: "Turn on camera" })).toBeInTheDocument();
  expect(camera.queryByText(/Loading the models/)).toBeNull();
  await waitFor(() => expect(sent.filter((request) => request.path === "/api/track/source").map((request) => request.body)).toEqual([{ picture: "browser" }]));
});

it("lets the owner pick the Pi's front or side camera for the room picture, only while the picture is the Pi's", async () => {
  const sent = serveSettings(OWNER, undefined, { "POST /api/track/source": answer({ source: "pi", picture: "pi", pi_camera: "side" }) });
  const user = renderSettings();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_source: "pi", picture_source: "pi", pi_camera: "front", side_camera_running: true })));
  const camera = await openSection(user, "Camera");
  const which = camera.getByRole("combobox", { name: "Which Pi camera" });
  expect(which).toHaveValue("front");
  expect(camera.getByRole("option", { name: "Side" })).toBeEnabled();

  await user.selectOptions(which, "side");

  expect(which).toHaveValue("side");
  await waitFor(() => expect(sent.filter((request) => request.path === "/api/track/source").map((request) => request.body)).toEqual([{ pi_camera: "side" }]));
  expect(camera.queryByText(/side camera isn’t running/)).toBeNull();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_source: "pi", picture_source: "browser" })));
  await waitFor(() => expect(camera.queryByRole("combobox", { name: "Which Pi camera" })).toBeNull());
});

it("greys out Side with a note while the side camera isn't running, since the tile falls back to the front", async () => {
  serveSettings(OWNER);
  const user = renderSettings();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_source: "pi", picture_source: "pi", pi_camera: "side", side_camera_running: false })));
  const camera = await openSection(user, "Camera");
  expect(camera.getByRole("option", { name: "Side" })).toBeDisabled();
  expect(camera.getByText("The side camera isn’t running, so your tile comes from the front one.")).toBeInTheDocument();
});

it("puts the pick back and says so when the Pi refuses it", async () => {
  serveSettings(OWNER, undefined, { "POST /api/track/source": answer({ detail: "only the owner's desk has the Pi's cameras" }, 403) });
  const user = renderSettings();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_source: "browser" })));
  const camera = await openSection(user, "Camera");
  const tracking = choicesFor(camera, "Track focus with");
  await user.click(tracking.getByRole("radio", { name: "This desk’s Pi cameras" }));
  expect(await camera.findByRole("alert")).toHaveTextContent("only the owner's desk has the Pi's cameras");
  expect(tracking.getByRole("radio", { name: "This browser’s camera" })).toBeChecked();
});

it("saves your own bedtime and where the peace sign speaks, and tests the voice there", async () => {
  const sent = serveSettings(MEMBER, [], {
    "POST /api/voice": answer({ bedtime: "23:15", output: "computer" }),
    "POST /api/voice/test": answer({ output: "computer", voice: true }),
  });
  const user = renderSettings();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ bedtime: "00:00", voice_output: "computer", voice: { enabled: true, backend: "piper", problem: null } })));
  const voice = await openSection(user, "Voice and bedtime");
  const bedtime = voice.getByLabelText("Bedtime");
  expect(bedtime).toHaveValue("00:00");
  expect(voice.getByRole("radio", { name: "The Pi’s speaker" })).toBeDisabled();
  expect(voice.getByRole("radio", { name: "This computer" })).toBeChecked();

  fireEvent.change(bedtime, { target: { value: "23:15" } });
  await user.click(voice.getByRole("button", { name: "Test the voice" }));

  expect(bedtime).toHaveValue("23:15");
  await waitFor(() =>
    expect(sent.filter((request) => request.path.startsWith("/api/voice")).map((request) => [request.path, request.body])).toEqual([
      ["/api/voice", { bedtime: "23:15" }],
      ["/api/voice/test", {}],
    ]),
  );
});

it("says how long to wait when the voice was tested a moment ago", async () => {
  serveSettings(MEMBER, [], { "POST /api/voice/test": answer({ detail: "one test every 10 s" }, 429, { "Retry-After": "8" }) });
  const user = renderSettings();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ voice_output: "computer", voice: { enabled: true, backend: "piper", problem: null } })));
  const voice = await openSection(user, "Voice and bedtime");
  await user.click(voice.getByRole("button", { name: "Test the voice" }));
  expect(await voice.findByRole("alert")).toHaveTextContent("Wait 8 s, then test it again.");
});

it("lets the owner move the peace sign from the Pi's speaker to this computer, and says when the voice is off", async () => {
  const sent = serveSettings(OWNER, undefined, { "POST /api/voice": answer({ bedtime: "22:30", output: "computer" }) });
  const user = renderSettings();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ bedtime: "22:30", voice_output: "pi", voice: { enabled: false, backend: "off", problem: null } })));
  const voice = await openSection(user, "Voice and bedtime");
  expect(voice.getByRole("radio", { name: "The Pi’s speaker" })).toBeChecked();
  expect(voice.getByText("The Pi's voice is off, so the peace sign shows its words and says nothing.")).toBeInTheDocument();
  await user.click(voice.getByRole("radio", { name: "This computer" }));
  expect(voice.getByRole("radio", { name: "This computer" })).toBeChecked();
  await waitFor(() => expect(sent.filter((request) => request.path === "/api/voice").map((request) => request.body)).toEqual([{ output: "computer" }]));
});

it("shows a new token's secret once, and revokes a token with a JSON DELETE", async () => {
  const made = { id: 8, name: "Work Mac", created_at: MADE + DAY, last_used_at: null };
  const sent = serveSettings(MEMBER, [], {
    "POST /api/tokens": answer({ token: made, secret: "dpi_secret-value" }),
    "DELETE /api/tokens/7": answer({ status: "ok" }),
  });
  const user = renderSettings();
  const mac = await openSection(user, "Mac helper");
  expect(await mac.findByText("MacBook")).toBeInTheDocument();

  await user.click(mac.getByRole("button", { name: "New token" }));
  await user.type(mac.getByLabelText("Token name"), "Work Mac");
  await user.click(mac.getByRole("button", { name: "Make it" }));

  expect(await mac.findByRole("textbox", { name: "New token" })).toHaveValue("dpi_secret-value");
  expect(mac.getByText("shown once")).toBeInTheDocument();
  expect(sent.at(-1)).toMatchObject({ method: "POST", path: "/api/tokens", body: { name: "Work Mac" } });
  expect(within(mac.getByRole("list", { name: "Tokens" })).getByText("Work Mac")).toBeInTheDocument();
  expect(within(mac.getByRole("list", { name: "Tokens" })).queryByText(/dpi_/)).toBeNull();

  await user.click(mac.getByRole("button", { name: "Revoke MacBook" }));

  expect(sent.at(-1)).toEqual({ method: "DELETE", path: "/api/tokens/7", headers: { "Content-Type": "application/json" }, body: {} });
  expect(mac.queryByText("MacBook")).toBeNull();
});

it("makes an invite and shows its whole link once", async () => {
  serveSettings(OWNER, undefined, { "POST /api/invites": answer({ invite: { id: 4, created_at: MADE + DAY, expires_at: MADE + 8 * DAY }, code: "abc_DEF-123" }) });
  const user = renderSettings();
  const room = await openSection(user, "Room and invites");
  await user.click(room.getByRole("button", { name: "New invite" }));
  expect(await room.findByRole("textbox", { name: "Invite link" })).toHaveValue(`${window.location.origin}/join/abc_DEF-123`);
  expect(within(room.getByRole("list", { name: "Open invites" })).getAllByRole("listitem")).toHaveLength(2);
});

it("says when the room is full", async () => {
  const four = [OWNER, MEMBER, { ...MEMBER, id: 3, username: "kim" }, { ...MEMBER, id: 4, username: "lee" }].map((account) => ({ ...account, created_at: MADE }));
  serveSettings(OWNER, four);
  const user = renderSettings();
  const room = await openSection(user, "Room and invites");
  expect(await room.findByText(/The room is full/)).toBeInTheDocument();
  expect(room.getByText("4 of 4 seats")).toBeInTheDocument();
  expect(room.getByRole("button", { name: "New invite" })).toBeDisabled();
});

it("removes a member only after a second click", async () => {
  const sent = serveSettings(OWNER, undefined, { "DELETE /api/accounts/2": answer({ status: "ok" }) });
  const user = renderSettings();
  const room = await openSection(user, "Room and invites");
  await user.click(await room.findByRole("button", { name: "Remove Sam" }));
  expect(sent.some((request) => request.method === "DELETE")).toBe(false);
  expect(room.queryByRole("button", { name: /Remove Dayan/ })).toBeNull();

  await user.click(room.getByRole("button", { name: "Yes, remove" }));

  expect(sent.at(-1)).toMatchObject({ method: "DELETE", path: "/api/accounts/2", body: {} });
  expect(room.queryByText("Sam")).toBeNull();
});

it("keeps keyboard focus in the row through both steps of a remove", async () => {
  serveSettings(OWNER);
  const user = renderSettings();
  const room = await openSection(user, "Room and invites");
  (await room.findByRole("button", { name: "Remove Sam" })).focus();

  await user.keyboard("{Enter}");
  const cancel = room.getByRole("button", { name: "Cancel" });
  expect(cancel).toHaveFocus();
  expect(cancel).toHaveAccessibleDescription("Their sign-ins and tokens stop working.");
  await user.tab({ shift: true });
  expect(room.getByRole("button", { name: "Yes, remove" })).toHaveFocus();

  await user.tab();
  await user.keyboard("{Enter}");
  expect(room.getByRole("button", { name: "Remove Sam" })).toHaveFocus();
});

it("saves the name, and asks for the current password only once you type a new one", async () => {
  const sent = serveSettings(MEMBER, [], {
    "PATCH /api/me": (body) => ({ status: 200, body: { user: { ...MEMBER, display_name: (body as { display_name: string }).display_name } } }),
    "POST /api/me/password": answer({ detail: "wrong password" }, 400),
  });
  const user = renderSettings();
  const name = await screen.findByLabelText("Name");
  await user.clear(name);
  await user.type(name, "Sammy");
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText("Saved.")).toBeInTheDocument();
  expect(sent.at(-1)).toMatchObject({ method: "PATCH", path: "/api/me", body: { display_name: "Sammy" } });
  expect(screen.getByRole("button", { name: "Account: Sammy" })).toBeInTheDocument();

  expect(screen.queryByLabelText("Current password")).toBeNull();
  await user.type(screen.getByLabelText("New password"), "a new long one");
  await user.type(screen.getByLabelText("Current password"), "not it at all");
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("wrong password");
  expect(sent.at(-1)).toMatchObject({ method: "POST", path: "/api/me/password", body: { current_password: "not it at all", new_password: "a new long one" } });
  expect(sent.filter((request) => request.method === "PATCH")).toHaveLength(1); // the name didn't change again
});

it("checks a new password's length before sending it", async () => {
  const sent = serveSettings(MEMBER, []);
  const user = renderSettings();
  await user.type(await screen.findByLabelText("New password"), "short");
  await user.type(screen.getByLabelText("Current password"), "whatever it is");
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("at least 10 characters");
  expect(sent.some((request) => request.path === "/api/me/password")).toBe(false);
});

it("signs out", async () => {
  const sent = serveSettings(MEMBER, [], { "POST /api/logout": answer({ status: "ok" }) });
  const user = renderSettings();
  await user.click(await screen.findByRole("button", { name: "Sign out" }));
  expect(sent.at(-1)).toMatchObject({ method: "POST", path: "/api/logout", body: {} });
  expect(loadPage).toHaveBeenCalledWith("/login");
});

it("shares with the room what the switches say, and previews your seat as the room gets it", async () => {
  const sharing = { focus: true, todos: true, history: true, apps: false, sites: false, video: false, nudges: true };
  const seat = makeSeat({ focus_seconds: 11538 });
  const sent = serveSettings(OWNER, undefined, {
    "POST /api/sharing": answer({ sharing: { ...sharing, apps: true }, seat: { ...seat, app: "Code" } }),
  });
  const user = renderSettings();
  FakeEventSource.latest?.send({ ...makeSnapshot(makeFocus({ sharing })), room: { seats: [seat] } });
  await user.click(await screen.findByRole("button", { name: "Sharing" }));
  const section = within(await screen.findByRole("region", { name: "Share with the room" }));

  expect(section.getByText("Always on")).toBeInTheDocument();
  const switches = section.getAllByRole("switch").map((entry) => [entry.getAttribute("aria-label"), entry.getAttribute("aria-checked")]);
  expect(switches).toEqual([
    ["Focus time", "true"],
    ["To-do list", "true"],
    ["History", "true"],
    ["Apps", "false"],
    ["Sites", "false"],
    ["Video", "false"],
    ["Nudges", "true"],
  ]);
  const pieces = () => section.getByRole("list", { name: "What else the room sees" }).textContent;
  expect(section.getByLabelText("Your seat: Dayan")).toHaveTextContent("Dayan02:05");
  expect(pieces()).toBe("3h 12m todayfinish the report");

  await user.click(section.getByRole("switch", { name: "Apps" }));

  expect(sent.at(-1)).toMatchObject({ method: "POST", path: "/api/sharing", body: { apps: true } });
  expect(section.getByRole("switch", { name: "Apps" })).toHaveAttribute("aria-checked", "true");
  await waitFor(() => expect(pieces()).toBe("3h 12m todayfinish the reportCode"));
});
