import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { JoinPage } from "@/components/auth/JoinPage";
import { loadPage } from "@/lib/navigation";
import { answer, serveApi, type Route as ApiRoute } from "@/test/fakeApi";
import { MEMBER } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

function renderJoin() {
  render(
    <MemoryRouter initialEntries={["/join/Inv1te_code-x"]}>
      <Routes>
        <Route path="/join/:code" element={<JoinPage />} />
      </Routes>
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  return user;
}

async function fillIn(user: ReturnType<typeof userEvent.setup>, password: string) {
  await user.type(screen.getByLabelText("Display name"), "Sam");
  await user.type(screen.getByLabelText("Username"), "sam");
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Join" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(loadPage).mockClear();
});

it("says the 10-character minimum before you type, and checks it before sending", async () => {
  const sent = serveApi({});
  const user = renderJoin();
  const password = screen.getByLabelText("Password");
  expect(password).toHaveAccessibleDescription("At least 10 characters.");
  expect(password).toHaveAttribute("autocomplete", "new-password");

  await fillIn(user, "short");

  expect(await screen.findByRole("alert")).toHaveTextContent("at least 10 characters");
  expect(sent).toEqual([]);
});

it("makes the account with the code from the link, then goes to the dashboard", async () => {
  const sent = serveApi({ "POST /api/join": answer({ user: MEMBER }) });
  const user = renderJoin();
  await fillIn(user, "a long password");
  expect(sent[0].body).toEqual({ code: "Inv1te_code-x", display_name: "Sam", username: "sam", password: "a long password" });
  expect(sent[0].headers).toEqual({ "Content-Type": "application/json" });
  expect(loadPage).toHaveBeenCalledWith("/");
});

it.each<[string, ApiRoute]>([
  ["this invite doesn't work any more", answer({ detail: "this invite doesn't work any more" }, 404)],
  ["the room is full", answer({ detail: "the room is full" }, 403)],
  ["that username is taken", answer({ detail: "that username is taken" }, 409)],
  [
    "username: a username is 2 to 32 of a-z, 0-9, _ . - and starts with a letter or a digit",
    answer({ detail: [{ type: "value_error", loc: ["body", "username"], msg: "Value error, a username is 2 to 32 of a-z, 0-9, _ . - and starts with a letter or a digit" }] }, 422),
  ],
])("shows the Pi's answer plainly: %s", async (shown, route) => {
  serveApi({ "POST /api/join": route });
  const user = renderJoin();
  await fillIn(user, "a long password");
  expect(await screen.findByRole("alert")).toHaveTextContent(shown);
  expect(loadPage).not.toHaveBeenCalled();
});
