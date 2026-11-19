import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { HIDDEN_CHECK_FOR_S, HIDDEN_CHECK_S, findTabIcon, showTabIcon, useTabIcon } from "@/hooks/useTabIcon";
import type { FocusState } from "@/lib/types";
import { answer, serveApi } from "@/test/fakeApi";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

let hidden = false;
const icon = () => document.querySelector('link[rel="icon"][type="image/svg+xml"]')?.getAttribute("href");

function hideTab(isHidden: boolean) {
  hidden = isHidden;
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  hidden = false;
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  document.head.innerHTML = '<link rel="icon" href="/assets/icon-working.svg" type="image/svg+xml">';
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(document, "hidden");
});

it("has an icon per state, and the gray one for unknown and signed out", () => {
  expect([findTabIcon("working"), findTabIcon("phone"), findTabIcon("away"), findTabIcon("unknown"), findTabIcon(null)]).toEqual([
    "/assets/icon-working.svg",
    "/assets/icon-phone.svg",
    "/assets/icon-away.svg",
    "/assets/icon-unknown.svg",
    "/assets/icon-unknown.svg",
  ]);
  showTabIcon(null);
  expect(icon()).toBe("/assets/icon-unknown.svg");
});

it("keeps index.html's icon until a state comes, then swaps it on every change", () => {
  const { rerender } = renderHook(({ state }: { state: FocusState | undefined }) => useTabIcon(state), { initialProps: { state: undefined as FocusState | undefined } });
  expect(icon()).toBe("/assets/icon-working.svg");
  rerender({ state: "phone" });
  expect(icon()).toBe("/assets/icon-phone.svg");
  rerender({ state: "away" });
  expect(icon()).toBe("/assets/icon-away.svg");
});

it("checks nothing while the tab shows, since the stream brings the state", async () => {
  const sent = serveApi({ "GET /api/focus": answer({ state: "phone" }) });
  renderHook(() => useTabIcon("working"));
  await act(() => vi.advanceTimersByTimeAsync(10 * 60 * 1000));
  expect(sent).toEqual([]);
});

it("checks the state every 10 s while the tab is hidden, for an hour, and hands back to the stream when it's back", async () => {
  const sent = serveApi({ "GET /api/focus": answer({ state: "phone" }) });
  renderHook(() => useTabIcon("working"));
  hideTab(true);
  await act(() => vi.advanceTimersByTimeAsync(HIDDEN_CHECK_S * 1000 - 1));
  expect(sent).toEqual([]);
  await act(() => vi.advanceTimersByTimeAsync(1));
  expect(sent.map((request) => request.path)).toEqual(["/api/focus"]);
  expect(icon()).toBe("/assets/icon-phone.svg"); // picked up the phone while in another tab

  await act(() => vi.advanceTimersByTimeAsync(HIDDEN_CHECK_FOR_S * 1000));
  expect(sent).toHaveLength(HIDDEN_CHECK_FOR_S / HIDDEN_CHECK_S);
  await act(() => vi.advanceTimersByTimeAsync(HIDDEN_CHECK_FOR_S * 1000));
  expect(sent).toHaveLength(HIDDEN_CHECK_FOR_S / HIDDEN_CHECK_S); // stopped after the hour

  hideTab(false);
  expect(icon()).toBe("/assets/icon-working.svg"); // the stream's again
  hideTab(true);
  await act(() => vi.advanceTimersByTimeAsync(HIDDEN_CHECK_S * 1000));
  expect(sent).toHaveLength(HIDDEN_CHECK_FOR_S / HIDDEN_CHECK_S + 1); // a new hour of checks
});
