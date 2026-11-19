import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import { LoginPage } from "@/components/auth/LoginPage";
import { Header } from "@/components/header/Header";
import { SignPage } from "@/components/sign/SignPage";
import { loadPage } from "@/lib/navigation";
import type { FocusState, User } from "@/lib/types";
import { answer, serveApi } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { MEMBER, OWNER, makeFocus, makeSnapshot } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

function renderHeader(user: User | null, lamp: FocusState | null = null) {
  render(
    <MemoryRouter initialEntries={["/me"]}>
      <Header connection="connected" lamp={lamp} user={user} phone={false} onOpenPalette={() => {}} />
    </MemoryRouter>,
  );
  const clicker = userEvent.setup();
  return clicker;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(loadPage).mockClear();
  window.localStorage.clear();
  document.documentElement.dataset.theme = "light";
});

it("shows who's signed in as a round initial, with Settings and Sign out in its menu", async () => {
  const sent = serveApi({ "POST /api/logout": answer({ status: "ok" }) });
  const user = renderHeader(OWNER);
  const account = screen.getByRole("button", { name: "Account: Dayan" });
  expect(account).toHaveTextContent(/^D$/);

  await user.click(account);

  expect(screen.getByRole("menuitem", { name: "Settings" })).toHaveAttribute("href", "/settings");
  await user.click(screen.getByRole("menuitem", { name: "Sign out" }));
  expect(sent).toEqual([{ method: "POST", path: "/api/logout", headers: { "Content-Type": "application/json" }, body: {} }]);
  expect(loadPage).toHaveBeenCalledWith("/login");
});

it("has no menu before /api/me answers, and no Pi tab until it says you're the owner", () => {
  renderHeader(null);
  expect(screen.queryByRole("button", { name: /^Account/ })).toBeNull();
  expect(screen.getByRole("link", { name: "Desk" })).toHaveAttribute("aria-current", "page");
  expect(screen.queryByRole("link", { name: "Pi" })).toBeNull();
});

it("never shows a member the Pi tab", () => {
  renderHeader(MEMBER);
  expect(screen.getByRole("button", { name: "Account: Sam" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Pi" })).toBeNull();
});

it("flips the theme from the sun/moon button and remembers it", async () => {
  const user = renderHeader(OWNER);

  await user.click(screen.getByRole("button", { name: "Switch to dark mode" }));

  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(window.localStorage.getItem("dayanpi.theme")).toBe("dark");
  await user.click(screen.getByRole("button", { name: "Switch to light mode" }));
  expect(document.documentElement.dataset.theme).toBe("light");
});

// The wordmark's d: its round part is the tab icon's lamp.
const lampColor = () => screen.getByRole("img", { name: "dayanpi" }).querySelector("circle")?.getAttribute("fill");

it.each([
  ["working", "#34d3b9"],
  ["phone", "#ff8a4c"],
  ["away", "#a99bff"],
  ["unknown", "#8e8e96"],
  [null, "#8e8e96"],
] as [FocusState | null, string][])("draws the wordmark's lamp for %s in the tab icon's color, read as dayanpi", (state, color) => {
  renderHeader(OWNER, state);
  expect(lampColor()).toBe(color);
  expect(screen.getByRole("img", { name: "dayanpi" })).toHaveTextContent("ayanpi");
});

it("lights the top bar's lamp from the same state as the tab icon, and the desk sign's too", async () => {
  vi.stubGlobal("EventSource", FakeEventSource);
  serveApi({ "GET /api/me": answer({ user: OWNER }), "GET /api/focus": answer({ segments: [] }) });
  const shown = render(
    <MemoryRouter initialEntries={["/me"]}>
      <App />
    </MemoryRouter>,
  );
  expect(lampColor()).toBe("#8e8e96"); // nothing from the stream yet
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ state: "phone" })));
  await waitFor(() => expect(lampColor()).toBe("#ff8a4c"));
  shown.unmount();

  render(<SignPage />);
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ state: "away" })));
  await waitFor(() => expect(lampColor()).toBe("#a99bff"));
});

it("keeps the lamp gray signed out", () => {
  render(
    <MemoryRouter initialEntries={["/login"]}>
      <LoginPage />
    </MemoryRouter>,
  );
  expect(lampColor()).toBe("#8e8e96");
});
