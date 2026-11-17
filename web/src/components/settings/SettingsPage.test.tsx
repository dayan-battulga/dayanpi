import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import { loadPage } from "@/lib/navigation";
import type { Account, User } from "@/lib/types";
import { answer, serveApi, type Route } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { MEMBER, OWNER } from "@/test/fixtures";

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

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(loadPage).mockClear();
});

it("shows the owner the invites and the accounts", async () => {
  serveSettings(OWNER);
  renderSettings();
  expect(await screen.findByRole("region", { name: "Invites" })).toBeInTheDocument();
  const accounts = within(screen.getByRole("region", { name: "Accounts" }));
  expect(await accounts.findByText("Sam")).toBeInTheDocument();
  expect(accounts.getByText("2 of 4")).toBeInTheDocument();
  expect(screen.getByLabelText("Display name")).toHaveValue("Dayan");
});

it("shows a member only their own things, and never asks for the owner's lists", async () => {
  const sent = serveSettings(MEMBER);
  renderSettings();
  expect(await screen.findByRole("region", { name: "Mac helper tokens" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Password" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Invites" })).toBeNull();
  expect(screen.queryByRole("region", { name: "Accounts" })).toBeNull();
  expect(sent.map((request) => request.path)).not.toContain("/api/invites");
  expect(sent.map((request) => request.path)).not.toContain("/api/accounts");
});

it("shows a new token's secret once, and revokes a token with a JSON DELETE", async () => {
  const made = { id: 8, name: "Work Mac", created_at: MADE + DAY, last_used_at: null };
  const sent = serveSettings(MEMBER, [], {
    "POST /api/tokens": answer({ token: made, secret: "dpi_secret-value" }),
    "DELETE /api/tokens/7": answer({ status: "ok" }),
  });
  const user = renderSettings();
  const panel = within(await screen.findByRole("region", { name: "Mac helper tokens" }));
  expect(await panel.findByText("MacBook")).toBeInTheDocument();

  await user.type(panel.getByLabelText("Token name"), "Work Mac");
  await user.click(panel.getByRole("button", { name: "Make a token" }));

  expect(await panel.findByRole("textbox", { name: "New token" })).toHaveValue("dpi_secret-value");
  expect(panel.getByText(/you won't see it again/)).toBeInTheDocument();
  expect(within(panel.getByRole("list", { name: "Tokens" })).getByText("Work Mac")).toBeInTheDocument();
  expect(within(panel.getByRole("list", { name: "Tokens" })).queryByText(/dpi_/)).toBeNull();

  await user.click(panel.getByRole("button", { name: "Revoke MacBook" }));

  expect(sent.at(-1)).toEqual({ method: "DELETE", path: "/api/tokens/7", headers: { "Content-Type": "application/json" }, body: {} });
  expect(panel.queryByText("MacBook")).toBeNull();
});

it("makes an invite and shows its whole link once", async () => {
  serveSettings(OWNER, undefined, { "POST /api/invites": answer({ invite: { id: 4, created_at: MADE + DAY, expires_at: MADE + 8 * DAY }, code: "abc_DEF-123" }) });
  const user = renderSettings();
  const panel = within(await screen.findByRole("region", { name: "Invites" }));
  await user.click(panel.getByRole("button", { name: "Make an invite" }));
  expect(await panel.findByRole("textbox", { name: "Invite link" })).toHaveValue(`${window.location.origin}/join/abc_DEF-123`);
  expect(within(panel.getByRole("list", { name: "Open invites" })).getAllByRole("listitem")).toHaveLength(2);
});

it("says when the room is full", async () => {
  const four = [OWNER, MEMBER, { ...MEMBER, id: 3, username: "kim" }, { ...MEMBER, id: 4, username: "lee" }].map((account) => ({ ...account, created_at: MADE }));
  serveSettings(OWNER, four);
  renderSettings();
  const panel = within(await screen.findByRole("region", { name: "Invites" }));
  expect(await panel.findByText(/The room is full/)).toBeInTheDocument();
  expect(panel.getByRole("button", { name: "Make an invite" })).toBeDisabled();
});

it("removes a member only after a second click", async () => {
  const sent = serveSettings(OWNER, undefined, { "DELETE /api/accounts/2": answer({ status: "ok" }) });
  const user = renderSettings();
  const panel = within(await screen.findByRole("region", { name: "Accounts" }));
  await user.click(await panel.findByRole("button", { name: "Remove Sam" }));
  expect(sent.some((request) => request.method === "DELETE")).toBe(false);
  expect(panel.queryByRole("button", { name: /Remove Dayan/ })).toBeNull();

  await user.click(panel.getByRole("button", { name: "Yes, remove" }));

  expect(sent.at(-1)).toMatchObject({ method: "DELETE", path: "/api/accounts/2", body: {} });
  expect(panel.queryByText("Sam")).toBeNull();
});

it("keeps keyboard focus in the row through both steps of a remove", async () => {
  serveSettings(OWNER);
  const user = renderSettings();
  const panel = within(await screen.findByRole("region", { name: "Accounts" }));
  (await panel.findByRole("button", { name: "Remove Sam" })).focus();

  await user.keyboard("{Enter}");
  const cancel = panel.getByRole("button", { name: "Cancel" });
  expect(cancel).toHaveFocus();
  expect(cancel).toHaveAccessibleDescription("Their sign-ins and tokens stop working.");
  await user.tab({ shift: true });
  expect(panel.getByRole("button", { name: "Yes, remove" })).toHaveFocus();

  await user.tab();
  await user.keyboard("{Enter}");
  expect(panel.getByRole("button", { name: "Remove Sam" })).toHaveFocus();
});

it("saves the display name and changes the password", async () => {
  const sent = serveSettings(MEMBER, [], {
    "PATCH /api/me": (body) => ({ status: 200, body: { user: { ...MEMBER, display_name: (body as { display_name: string }).display_name } } }),
    "POST /api/me/password": answer({ detail: "wrong password" }, 400),
  });
  const user = renderSettings();
  const name = await screen.findByLabelText("Display name");
  await user.clear(name);
  await user.type(name, "Sammy");
  await user.click(screen.getByRole("button", { name: "Save name" }));
  expect(await screen.findByText("Saved.")).toBeInTheDocument();
  expect(sent.at(-1)).toMatchObject({ method: "PATCH", path: "/api/me", body: { display_name: "Sammy" } });
  expect(screen.getByRole("button", { name: "Account: Sammy" })).toBeInTheDocument();

  await user.type(screen.getByLabelText("Current password"), "not it at all");
  await user.type(screen.getByLabelText("New password"), "a new long one");
  await user.click(screen.getByRole("button", { name: "Change password" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("wrong password");
  expect(sent.at(-1)).toMatchObject({ body: { current_password: "not it at all", new_password: "a new long one" } });
});

it("signs out", async () => {
  const sent = serveSettings(MEMBER, [], { "POST /api/logout": answer({ status: "ok" }) });
  const user = renderSettings();
  await user.click(await screen.findByRole("button", { name: "Sign out" }));
  expect(sent.at(-1)).toMatchObject({ method: "POST", path: "/api/logout", body: {} });
  expect(loadPage).toHaveBeenCalledWith("/login");
});
