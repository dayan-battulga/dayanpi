import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { Header } from "@/components/header/Header";
import { loadPage } from "@/lib/navigation";
import type { User } from "@/lib/types";
import { answer, serveApi } from "@/test/fakeApi";
import { MEMBER, OWNER } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

function renderHeader(user: User | null) {
  render(
    <MemoryRouter initialEntries={["/me"]}>
      <Header connection="connected" user={user} phone={false} />
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
