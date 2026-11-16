import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { Header } from "@/components/header/Header";
import { loadPage } from "@/lib/navigation";
import { answer, serveApi } from "@/test/fakeApi";
import { OWNER } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(loadPage).mockClear();
});

it("shows who's signed in, with Settings and Sign out in its menu", async () => {
  const sent = serveApi({ "POST /api/logout": answer({ status: "ok" }) });
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <Header connection="connected" undervoltage={false} user={OWNER} piShown />
    </MemoryRouter>,
  );

  await user.click(screen.getByRole("button", { name: "Dayan" }));

  expect(screen.getByRole("menuitem", { name: "Settings" })).toHaveAttribute("href", "/settings");
  await user.click(screen.getByRole("menuitem", { name: "Sign out" }));
  expect(sent).toEqual([{ method: "POST", path: "/api/logout", headers: { "Content-Type": "application/json" }, body: {} }]);
  expect(loadPage).toHaveBeenCalledWith("/login");
});

it("has no menu before /api/me answers, and no Pi link for a member", () => {
  render(
    <MemoryRouter>
      <Header connection="disconnected" undervoltage={false} user={null} piShown={false} />
    </MemoryRouter>,
  );
  expect(screen.queryByRole("button", { name: "Dayan" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Pi" })).toBeNull();
  expect(screen.getByRole("link", { name: "Focus" })).toBeInTheDocument();
});
