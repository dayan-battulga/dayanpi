import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { LoginPage } from "@/components/auth/LoginPage";
import { loadPage } from "@/lib/navigation";
import { answer, serveApi } from "@/test/fakeApi";
import { OWNER } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

function renderLogin(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <LoginPage />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  return user;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(loadPage).mockClear();
});

it("signs in and goes back to where you were", async () => {
  const sent = serveApi({ "POST /api/login": answer({ user: OWNER }) });
  const user = renderLogin("/login?next=%2Fsettings");
  expect(screen.getByLabelText("Username")).toHaveAttribute("autocomplete", "username");
  expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");

  await user.type(screen.getByLabelText("Username"), "dayan");
  await user.type(screen.getByLabelText("Password"), "correct horse");
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  expect(sent).toEqual([
    { method: "POST", path: "/api/login", headers: { "Content-Type": "application/json" }, body: { username: "dayan", password: "correct horse" } },
  ]);
  expect(loadPage).toHaveBeenCalledWith("/settings");
});

it("shows the Pi's answer when it says no, and stays", async () => {
  serveApi({ "POST /api/login": answer({ detail: "wrong username or password" }, 401) });
  const user = renderLogin("/login");
  await user.type(screen.getByLabelText("Username"), "dayan");
  await user.type(screen.getByLabelText("Password"), "nope");
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("wrong username or password");
  expect(loadPage).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
});

it("never follows next off the site", async () => {
  serveApi({ "POST /api/login": answer({ user: OWNER }) });
  const user = renderLogin("/login?next=%2F%2Fevil.com");
  await user.type(screen.getByLabelText("Username"), "dayan");
  await user.type(screen.getByLabelText("Password"), "correct horse");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  expect(loadPage).toHaveBeenCalledWith("/");
});
