import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TodoCard } from "@/components/todo/TodoCard";
import type { Todos } from "@/lib/types";
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
      return { ok: true, json: async () => ({ todos: structuredClone(todos) }) };
    }),
  );
}

function renderCard() {
  render(<TodoCard todos={TODOS} known={[]} now={Date.now() / 1000} />);
  const user = userEvent.setup();
  return user;
}

beforeEach(() => {
  sent = [];
  serveTodos(TODOS);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("shows each item's time, and a dash before it has any", () => {
  renderCard();
  const open = within(screen.getByRole("list", { name: "To-do" }));
  expect(open.getAllByRole("listitem")[0]).toHaveTextContent("finish the report12m");
  expect(open.getAllByRole("listitem")[1]).toHaveTextContent("reply to emails—");
  expect(screen.getByRole("button", { name: "Stop working on: finish the report" })).toHaveAttribute("aria-pressed", "true");
});

it("adds an item", async () => {
  const user = renderCard();
  await user.type(screen.getByRole("textbox", { name: "New to-do" }), "  do laundry {Enter}");
  expect(sent).toEqual([{ method: "POST", url: "/api/todos", body: { text: "do laundry" } }]);
  expect(await screen.findByText("do laundry")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "New to-do" })).toHaveValue("");
});

it("checking moves an item to Done, and unchecking moves it back", async () => {
  const user = renderCard();
  await user.click(screen.getByRole("checkbox", { name: "Done: finish the report" }));
  expect(sent[0]).toEqual({ method: "PATCH", url: "/api/todos/a1", body: { done: true } });
  const done = within(await screen.findByRole("list", { name: "Done today" }));
  expect(done.getByText("finish the report")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Done today" })).toBeInTheDocument();

  await user.click(done.getByRole("checkbox", { name: "Not done: finish the report" }));
  expect(sent[1]).toEqual({ method: "PATCH", url: "/api/todos/a1", body: { done: false } });
  expect(await within(screen.getByRole("list", { name: "To-do" })).findByText("finish the report")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Done today" })).toBeNull();
});

it("makes another item the current one", async () => {
  const user = renderCard();
  await user.click(screen.getByRole("button", { name: "Work on: reply to emails" }));
  expect(sent[0]).toEqual({ method: "PATCH", url: "/api/todos/b2", body: { current: true } });
  expect(await screen.findByRole("button", { name: "Stop working on: reply to emails" })).toHaveAttribute("aria-pressed", "true");
});

it("edits an item with Enter, and Esc leaves it alone", async () => {
  const user = renderCard();
  await user.click(screen.getByRole("button", { name: "reply to emails" }));
  await user.keyboard("{Escape}");
  expect(sent).toEqual([]);
  await user.click(screen.getByRole("button", { name: "finish the report" }));
  const input = screen.getByRole("textbox", { name: "Edit: finish the report" });
  await user.clear(input);
  await user.type(input, "finish the big report{Enter}");
  expect(sent).toEqual([{ method: "PATCH", url: "/api/todos/a1", body: { text: "finish the big report" } }]);
  expect(await screen.findByRole("button", { name: "finish the big report" })).toBeInTheDocument();
});

it("deletes an item", async () => {
  const user = renderCard();
  await user.click(screen.getByRole("button", { name: "Delete: reply to emails" }));
  expect(sent).toEqual([{ method: "DELETE", url: "/api/todos/b2", body: undefined }]);
  await vi.waitFor(() => expect(screen.queryByText("reply to emails")).toBeNull());
});
