import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionConfig } from "motion/react";
import { toast } from "sonner";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TodoList } from "@/components/todo/TodoList";
import { Toaster } from "@/components/ui/toaster";
import type { FocusState, Todos } from "@/lib/types";
import { TODOS } from "@/test/fixtures";

interface SentRequest {
  method: string;
  url: string;
  body: Record<string, unknown> | undefined;
}

let sent: SentRequest[] = [];

// A tiny stand-in for /api/todos that answers like app.py: the whole list after each change.
function serveTodos(initial: Todos) {
  const todos: Todos = structuredClone(initial);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      const body = init.body == null ? undefined : JSON.parse(init.body as string);
      sent.push({ method, url, body });
      const id = url.split("/").pop();
      const item = [...todos.open, ...todos.done].find((entry) => entry.id === id);
      if (method === "POST") {
        todos.open.push({ id: "c3", text: body.text, seconds: 0, done_at: null });
      } else if (method === "DELETE") {
        todos.open = todos.open.filter((entry) => entry.id !== id);
      } else if (item != null && body.done !== undefined) {
        todos.open = body.done ? todos.open.filter((entry) => entry.id !== id) : [...todos.open, { ...item, done_at: null }];
        todos.done = body.done ? [{ ...item, done_at: 1 }] : todos.done.filter((entry) => entry.id !== id);
        todos.current = body.done && todos.current === id ? null : todos.current;
      } else if (item != null && body.current !== undefined) {
        todos.current = body.current ? item.id : null;
      } else if (item != null) {
        item.text = body.text;
      }
      return { ok: true, status: 200, json: async () => ({ todos: structuredClone(todos) }) };
    }),
  );
}

// The Pi never answers: whatever shows is the page's own guess.
function holdTodos() {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => {})),
  );
}

function renderList({ todos = TODOS, state = "working" }: { todos?: Todos; state?: FocusState } = {}) {
  render(
    <>
      <TodoList todos={todos} state={state} now={Date.now() / 1000} />
      <Toaster />
    </>,
  );
  const user = userEvent.setup();
  return user;
}

const openRows = () => within(screen.getByRole("list", { name: "To-do" })).queryAllByRole("listitem");
const doneRows = () => within(screen.getByRole("list", { name: "Done" })).queryAllByRole("listitem");
const readHint = () => document.querySelector(".todos-hint")?.textContent;

beforeEach(() => {
  sent = [];
  serveTodos(TODOS);
});

afterEach(() => {
  vi.unstubAllGlobals();
  toast.dismiss();
});

it("shows each row's time, a dash before it has any, and the current row tinted", () => {
  renderList();
  expect(openRows()[0]).toHaveTextContent("finish the report12m");
  expect(openRows()[1]).toHaveTextContent("reply to emails—");
  expect(openRows()[0]).toHaveAttribute("data-current");
  expect(openRows()[1]).not.toHaveAttribute("data-current");
});

it.each([
  ["working", "Working"],
  ["phone", "Paused"],
  ["away", "Paused"],
  ["unknown", "Paused"],
] as const)("says %s on the current row as %s, and Start on the others", (state, pill) => {
  renderList({ state });
  const current = screen.getByRole("button", { name: "Stop working on finish the report" });
  expect(current).toHaveTextContent(pill);
  expect(current).toHaveAttribute("aria-pressed", "true");
  expect(current.hasAttribute("data-working")).toBe(state === "working");
  expect(screen.getByRole("button", { name: "Work on reply to emails" })).toHaveTextContent("Start");
});

it("starts another row right away, and it becomes the only current one", async () => {
  holdTodos();
  const user = renderList();
  await user.click(screen.getByRole("button", { name: "Work on reply to emails" }));
  expect(screen.getByRole("button", { name: "Stop working on reply to emails" })).toHaveTextContent("Working");
  expect(screen.getByRole("button", { name: "Work on finish the report" })).toHaveTextContent("Start");
  expect(openRows()[1]).toHaveAttribute("data-current");
});

it("sends Start and Working/Paused as the make-current API", async () => {
  const user = renderList();
  await user.click(screen.getByRole("button", { name: "Work on reply to emails" }));
  await user.click(await screen.findByRole("button", { name: "Stop working on reply to emails" }));
  expect(sent.map((request) => [request.method, request.url, request.body])).toEqual([
    ["PATCH", "/api/todos/b2", { current: true }],
    ["PATCH", "/api/todos/b2", { current: false }],
  ]);
});

it("stops the current row from its pill, leaving every row with Start and a nudge to start one", async () => {
  holdTodos();
  const user = renderList({ state: "phone" });
  await user.click(screen.getByRole("button", { name: "Stop working on finish the report" }));
  expect(screen.queryByRole("button", { name: /^Stop working on/ })).toBeNull();
  expect(screen.getAllByRole("button", { name: /^Work on/ })).toHaveLength(2);
  expect(readHint()).toBe("Start one to collect its time");
});

it("moves a checked row down into Done right away, and unchecking moves it back", async () => {
  holdTodos();
  const user = renderList();
  await user.click(screen.getByRole("checkbox", { name: "Done: finish the report" }));
  expect(openRows().map((row) => row.textContent)).toEqual(["reply to emails—Start"]);
  expect(doneRows()).toHaveLength(1);
  expect(doneRows()[0]).toHaveTextContent("finish the report12m");
  expect(doneRows()[0]).toHaveAttribute("data-done");
  expect(screen.getByRole("heading", { name: "Done" })).toBeInTheDocument();

  await user.click(within(doneRows()[0]).getByRole("checkbox", { name: "Not done: finish the report" }));
  expect(doneRows()).toHaveLength(0);
  expect(openRows().map((row) => within(row).getByRole("button", { name: /^(reply|finish)/ }).textContent)).toEqual(["reply to emails", "finish the report"]);
  expect(screen.queryByRole("heading", { name: "Done" })).toBeNull();
});

it("sends checking and unchecking, and a checked row stops being current", async () => {
  const user = renderList();
  await user.click(screen.getByRole("checkbox", { name: "Done: finish the report" }));
  await user.click(await screen.findByRole("checkbox", { name: "Not done: finish the report" }));
  expect(sent.map((request) => request.body)).toEqual([{ done: true }, { done: false }]);
  await waitFor(() => expect(screen.getByRole("button", { name: "Work on finish the report" })).toBeInTheDocument());
});

it("adds a row with Enter once the Pi gives it an id, and empties the box", async () => {
  const user = renderList();
  await user.type(screen.getByRole("textbox", { name: "New to-do" }), "  do laundry {Enter}");
  expect(sent).toEqual([{ method: "POST", url: "/api/todos", body: { text: "do laundry" } }]);
  expect(await screen.findByRole("button", { name: "do laundry" })).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "New to-do" })).toHaveValue("");
});

it("gives the text back and says so when adding fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 500, json: async () => ({ detail: "boom" }) })),
  );
  const user = renderList();
  await user.type(screen.getByRole("textbox", { name: "New to-do" }), "do laundry{Enter}");
  expect(await screen.findByText("Couldn't add that to-do")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "New to-do" })).toHaveValue("do laundry");
});

it("deletes a row from its × right away", async () => {
  holdTodos();
  const user = renderList();
  await user.click(screen.getByRole("button", { name: "Delete reply to emails" }));
  expect(screen.queryByText("reply to emails")).toBeNull();
});

it("sends the delete", async () => {
  const user = renderList();
  await user.click(screen.getByRole("button", { name: "Delete reply to emails" }));
  expect(sent).toEqual([{ method: "DELETE", url: "/api/todos/b2", body: {} }]);
});

it("puts the row back and shows a toast when a save fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }),
  );
  const user = renderList();
  await user.click(screen.getByRole("checkbox", { name: "Done: finish the report" }));
  expect(await screen.findByText("Couldn't save that change")).toBeInTheDocument();
  expect(openRows()[0]).toHaveTextContent("finish the report");
  expect(doneRows()).toHaveLength(0);
});

it("counts the open rows next to the title, rolling", async () => {
  holdTodos();
  const user = renderList();
  expect(document.querySelector(".todos-hint .sr-only")).toHaveTextContent("2 open");
  expect(document.querySelectorAll(".todos-hint number-flow-react")).toHaveLength(1);
  await user.click(screen.getByRole("checkbox", { name: "Done: reply to emails" }));
  expect(document.querySelector(".todos-hint .sr-only")).toHaveTextContent("1 open");
});

it("edits a row's text with Enter, and Esc leaves it alone", async () => {
  const user = renderList();
  await user.click(screen.getByRole("button", { name: "reply to emails" }));
  await user.keyboard("{Escape}");
  expect(sent).toEqual([]);
  await user.click(screen.getByRole("button", { name: "finish the report" }));
  const input = screen.getByRole("textbox", { name: "Edit: finish the report" });
  await user.clear(input);
  await user.type(input, "finish the big report{Enter}");
  expect(sent).toEqual([{ method: "PATCH", url: "/api/todos/a1", body: { text: "finish the big report" } }]);
  expect(screen.getByRole("button", { name: "finish the big report" })).toBeInTheDocument();
});

const ONE_LEFT: Todos = { current: null, open: [{ id: "a1", text: "finish the report", seconds: 754, done_at: null }], done: [{ id: "b2", text: "reply to emails", seconds: 60, done_at: 1 }] };
const confetti = () => document.querySelectorAll(".confetti span").length;

it("throws one burst of confetti and says All done once the last open row is checked, until a new one comes in", async () => {
  const user = renderList();
  await user.click(screen.getByRole("checkbox", { name: "Done: finish the report" }));
  expect(screen.queryByText("All done. Nice.")).toBeNull(); // one still open
  await user.click(screen.getByRole("checkbox", { name: "Done: reply to emails" }));
  expect(screen.getByText("All done. Nice.")).toBeInTheDocument();
  expect(confetti()).toBe(16);

  await user.type(screen.getByRole("textbox", { name: "New to-do" }), "one more{Enter}");
  await waitFor(() => expect(openRows()).toHaveLength(1));
  expect(screen.queryByText("All done. Nice.")).toBeNull();
  expect(confetti()).toBe(0);
});

it("never says All done on load, for a list that was empty, or when the last row is deleted", async () => {
  renderList({ todos: { current: null, open: [], done: ONE_LEFT.done } });
  expect(screen.queryByText("All done. Nice.")).toBeNull();
  cleanup();

  holdTodos();
  const user = renderList({ todos: ONE_LEFT });
  await user.click(screen.getByRole("button", { name: "Delete finish the report" }));
  expect(openRows()).toHaveLength(0);
  expect(screen.queryByText("All done. Nice.")).toBeNull();
  expect(confetti()).toBe(0);
});

it("says All done without the confetti with reduced motion", async () => {
  holdTodos();
  render(
    <MotionConfig reducedMotion="always">
      <TodoList todos={ONE_LEFT} state="working" now={Date.now() / 1000} />
    </MotionConfig>,
  );
  await userEvent.setup().click(screen.getByRole("checkbox", { name: "Done: finish the report" }));
  expect(screen.getByText("All done. Nice.")).toBeInTheDocument();
  expect(confetti()).toBe(0);
});
