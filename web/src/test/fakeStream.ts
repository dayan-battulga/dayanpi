import { act } from "@testing-library/react";

// A stand-in for the browser's EventSource behind /api/stream: tests push snapshots and drop the connection.
export class FakeEventSource {
  static readonly CLOSED = 2;
  static latest: FakeEventSource | null = null;
  readyState = 1;
  closed = false;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    FakeEventSource.latest = this;
  }

  close() {
    this.closed = true;
  }

  send(data: object) {
    act(() => this.onmessage?.({ data: JSON.stringify(data) }));
  }

  // A dropped connection the browser retries (0, connecting), or a non-200 answer it gives up on (2, closed).
  fail(readyState = 0) {
    this.readyState = readyState;
    act(() => this.onerror?.());
  }
}
