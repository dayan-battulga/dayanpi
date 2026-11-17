import { render, screen, waitFor } from "@testing-library/react";
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
  vi.restoreAllMocks();
  vi.mocked(loadPage).mockClear();
});

async function signIn(user: ReturnType<typeof userEvent.setup>, password: string) {
  await user.type(screen.getByLabelText("Username"), "dayan");
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

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

it("says so on a wrong password, rings the box, shakes on every miss, and stays", async () => {
  serveApi({ "POST /api/login": answer({ detail: "wrong username or password" }, 401) });
  const animate = vi.spyOn(Element.prototype, "animate");
  const user = renderLogin("/login");
  await signIn(user, "nope");

  expect(await screen.findByRole("alert")).toHaveTextContent("Wrong username or password.");
  expect(screen.getByLabelText("Password")).toHaveAttribute("aria-invalid", "true");
  expect(loadPage).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();

  await user.click(screen.getByRole("button", { name: "Sign in" })); // the next miss shakes again
  await waitFor(() => expect(animate).toHaveBeenCalledTimes(2));
  const [frames, options] = animate.mock.calls[0];
  expect((frames as Keyframe[]).map((frame) => frame.transform)).toEqual(["translateX(0px)", "translateX(-7px)", "translateX(6px)", "translateX(-4px)", "translateX(2px)", "translateX(0px)"]);
  expect(options).toEqual({ duration: 500, easing: "ease-in-out" });
});

it("doesn't shake with reduced motion", async () => {
  serveApi({ "POST /api/login": answer({ detail: "wrong username or password" }, 401) });
  const realMatchMedia = window.matchMedia;
  vi.spyOn(window, "matchMedia").mockImplementation((query) => ({ ...realMatchMedia(query), matches: query.includes("reduce") }));
  const animate = vi.spyOn(Element.prototype, "animate");
  const user = renderLogin("/login");
  await signIn(user, "nope");
  expect(await screen.findByRole("alert")).toHaveTextContent("Wrong username or password.");
  expect(animate).not.toHaveBeenCalled();
});

it("waits out the lockout: the time left in warm, the button dimmed, and back when it's over", async () => {
  serveApi({ "POST /api/login": answer({ detail: "too many tries, wait a bit" }, 429, { "Retry-After": "1" }) });
  const animate = vi.spyOn(Element.prototype, "animate");
  const user = renderLogin("/login");
  await signIn(user, "correct horse");

  const locked = await screen.findByRole("alert");
  expect(locked).toHaveTextContent("Too many tries. Try again in 0:01");
  expect(locked).toHaveAttribute("data-tone", "warn");
  expect(locked.querySelector(".sr-only")).toHaveTextContent("1 seconds");
  expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
  expect(screen.getByLabelText("Password")).not.toHaveAttribute("aria-invalid");
  expect(animate).not.toHaveBeenCalled();

  await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled(), { timeout: 3000 });
  expect(screen.queryByRole("alert")).toBeNull();
});

it("never follows next off the site", async () => {
  serveApi({ "POST /api/login": answer({ user: OWNER }) });
  const user = renderLogin("/login?next=%2F%2Fevil.com");
  await user.type(screen.getByLabelText("Username"), "dayan");
  await user.type(screen.getByLabelText("Password"), "correct horse");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  expect(loadPage).toHaveBeenCalledWith("/");
});
