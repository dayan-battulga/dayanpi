import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { readSafeNext, request } from "@/lib/http";
import { loadPage } from "@/lib/navigation";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

function stubReply(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => ({ ok: status >= 200 && status < 300, status, json: async () => body }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  window.history.pushState({}, "", "/settings?tab=tokens");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(loadPage).mockClear();
});

it("follows next only to a path on this site", () => {
  expect(readSafeNext("/settings?tab=tokens")).toBe("/settings?tab=tokens");
  expect(readSafeNext("/")).toBe("/");
  expect(readSafeNext("//evil.com")).toBe("/");
  expect(readSafeNext("/\\evil.com")).toBe("/");
  expect(readSafeNext("https://evil.com")).toBe("/");
  expect(readSafeNext("evil.com")).toBe("/");
  expect(readSafeNext("")).toBe("/");
  expect(readSafeNext(null)).toBe("/");
  expect(readSafeNext("//[")).toBe("/");
});

// What the Pi's own redirect builds for GET /%09/evil.example: the URL parser drops the tab and reads //evil.example.
it.each(["%2F%09%2Fevil.example%2Fphish", "%2F%0A%2Fevil.example", "%2F%0D%2Fevil.example", "%2F%09%5Cevil.example"])(
  "never follows next=%s to another host",
  (encoded) => {
    expect(readSafeNext(new URLSearchParams(`next=${encoded}`).get("next"))).toBe("/");
  },
);

// These stay on this origin, but the parser drops the "." or "x/.." and the path it leaves starts with //.
it.each(["/.//evil.example/login", "/a/..//evil.example", "/./\\evil.example", "/%2e//evil.example", "/x/%2E%2E//evil.example?a=1#b"])(
  "never follows next=%s to a path that starts with //",
  (next) => {
    expect(readSafeNext(next)).toBe("/");
  },
);

it("sends a 401 to /login, with where you were as next", async () => {
  stubReply(401, { detail: "sign in first" });
  const reply = await request("GET", "/api/focus");
  expect(reply).toEqual({ ok: false, status: 401, body: null, detail: "sign in first", retryAfterS: null });
  expect(loadPage).toHaveBeenCalledWith("/login?next=%2Fsettings%3Ftab%3Dtokens");
});

it("leaves a wrong password or a bad invite on the page", async () => {
  stubReply(401, { detail: "wrong username or password" });
  const login = await request("POST", "/api/login", { username: "dayan", password: "nope" });
  stubReply(404, { detail: "this invite doesn't work any more" });
  const join = await request("POST", "/api/join", { code: "x" });
  expect(login.detail).toBe("wrong username or password");
  expect(join.detail).toBe("this invite doesn't work any more");
  expect(loadPage).not.toHaveBeenCalled();
});

it("sends every write as JSON, with {} when there's nothing to say", async () => {
  const fetchMock = stubReply(200, { status: "ok" });
  await request("POST", "/api/todos", { text: "laundry" });
  await request("DELETE", "/api/tokens/7");
  await request("POST", "/api/logout");
  await request("GET", "/api/me");
  const [post, remove, logout, get] = fetchMock.mock.calls.map((call) => (call as unknown[])[1] as RequestInit);
  expect(post).toMatchObject({ method: "POST", headers: { "Content-Type": "application/json" }, body: '{"text":"laundry"}' });
  expect(remove).toMatchObject({ method: "DELETE", headers: { "Content-Type": "application/json" }, body: "{}" });
  expect(logout).toMatchObject({ method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  expect(get.method).toBe("GET");
  expect(get.body).toBeUndefined();
});

it("reads a 422's list of problems as one line", async () => {
  stubReply(422, { detail: [{ loc: ["body", "new_password"], msg: "String should have at least 10 characters" }] });
  const reply = await request("POST", "/api/me/password", { current_password: "a", new_password: "b" });
  expect(reply.detail).toBe("new password: String should have at least 10 characters");
});

it("drops pydantic's 'Value error, ' from the Pi's own checks", async () => {
  stubReply(422, { detail: [{ type: "value_error", loc: ["body", "display_name"], msg: "Value error, a display name is 1 to 40 characters, with no control characters" }] });
  const reply = await request("PATCH", "/api/me", { display_name: "" });
  expect(reply.detail).toBe("display name: a display name is 1 to 40 characters, with no control characters");
});

it("says status 0 when nothing answered", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
  const reply = await request("GET", "/api/me");
  expect(reply).toEqual({ ok: false, status: 0, body: null, detail: null, retryAfterS: null });
  expect(loadPage).not.toHaveBeenCalled();
});

it("reads how long a 429 says to wait", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 429, headers: new Headers({ "Retry-After": "28" }), json: async () => ({ detail: "too many tries, wait a bit" }) })));
  const reply = await request("POST", "/api/login", {});
  expect([reply.status, reply.detail, reply.retryAfterS]).toEqual([429, "too many tries, wait a bit", 28]);
});
