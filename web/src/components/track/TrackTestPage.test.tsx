import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { TrackTestPage } from "@/components/track/TrackTestPage";

function renderPage() {
  render(
    <MemoryRouter initialEntries={["/track/test"]}>
      <TrackTestPage />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  return user;
}

// Chrome's frame reader, which the page checks for first.
function pretendChrome(getUserMedia: (() => Promise<MediaStream>) | null) {
  vi.stubGlobal("MediaStreamTrackProcessor", class {});
  Object.defineProperty(navigator, "mediaDevices", { value: getUserMedia === null ? undefined : { getUserMedia }, configurable: true });
}

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
});

it("waits for a click before asking for the camera", async () => {
  const getUserMedia = vi.fn(() => Promise.reject(new DOMException("denied", "NotAllowedError")));
  pretendChrome(getUserMedia);
  const user = renderPage();
  expect(getUserMedia).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Start the test" }));
  expect(getUserMedia).toHaveBeenCalledWith({ video: { width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
});

it.each([
  ["blocked", () => Promise.reject(new DOMException("denied", "NotAllowedError")), "The camera is blocked."],
  ["missing", () => Promise.reject(new DOMException("none", "NotFoundError")), "No camera found."],
  ["in use", () => Promise.reject(new DOMException("busy", "NotReadableError")), "Another app is using the camera."],
  ["not there at all", null, "No camera found."],
])("says what's wrong when the camera is %s, and offers Start again", async (_, getUserMedia, message) => {
  pretendChrome(getUserMedia);
  const user = renderPage();
  await user.click(screen.getByRole("button", { name: "Start the test" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(screen.getByRole("button", { name: "Start the test" })).toBeEnabled();
  expect(screen.queryByText("Results")).not.toBeInTheDocument();
});

it("says it needs Chrome without asking for the camera", async () => {
  const getUserMedia = vi.fn(() => Promise.reject(new Error("never asked")));
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
  const user = renderPage();
  await user.click(screen.getByRole("button", { name: "Start the test" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("This test needs Chrome");
  expect(getUserMedia).not.toHaveBeenCalled();
});
