import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import { loadPage } from "@/lib/navigation";
import type { Account, User } from "@/lib/types";
import { answer, serveApi, type Route } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { MEMBER, OWNER, makeFocus, makeSnapshot } from "@/test/fixtures";

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

const sectionNames = () => within(screen.getByRole("navigation", { name: "Settings sections" })).getAllByRole("listitem").map((item) => item.textContent);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(loadPage).mockClear();
});

it("starts on Profile, and the list picks a section, marked, rising in fresh", async () => {
  serveSettings(OWNER);
  const user = renderSettings();
  expect(await screen.findByRole("region", { name: "Profile" })).toBeInTheDocument();
  expect(sectionNames()).toEqual(["Profile", "Camera", "Mac helper", "Room and invites"]);
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
  expect(sectionNames()).toEqual(["Profile", "Camera", "Mac helper"]);
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
  expect(camera.getByRole("radio", { name: "This desk’s Pi cameras" })).toBeChecked();

  await user.click(camera.getByRole("radio", { name: "This browser’s camera" }));

  expect(camera.getByRole("radio", { name: "This browser’s camera" })).toBeChecked();
  expect(camera.getByRole("link", { name: "the tracker" })).toHaveAttribute("href", "/track");
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
  await user.click(pi);
  expect(sent.map((request) => request.path)).not.toContain("/api/track/source");
});

it("puts the pick back and says so when the Pi refuses it", async () => {
  serveSettings(OWNER, undefined, { "POST /api/track/source": answer({ detail: "only the owner's desk has the Pi's cameras" }, 403) });
  const user = renderSettings();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_source: "browser" })));
  const camera = await openSection(user, "Camera");
  await user.click(camera.getByRole("radio", { name: "This desk’s Pi cameras" }));
  expect(await camera.findByRole("alert")).toHaveTextContent("only the owner's desk has the Pi's cameras");
  expect(camera.getByRole("radio", { name: "This browser’s camera" })).toBeChecked();
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
