import { vi } from "vitest";

export interface SentRequest {
  method: string;
  path: string;
  headers: Record<string, string> | undefined;
  body: unknown;
}

export type Route = (body: unknown) => { status: number; body: unknown };

// A stand-in for the Pi's API: "METHOD /path" -> what it answers. Anything else is a 404.
// Every request lands in the returned list, with its parsed JSON body.
export function serveApi(routes: Record<string, Route>): SentRequest[] {
  const sent: SentRequest[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      const body = init.body == null ? undefined : JSON.parse(String(init.body));
      sent.push({ method, path, headers: init.headers as Record<string, string> | undefined, body });
      const route = routes[`${method} ${path}`];
      const reply = route == null ? { status: 404, body: { detail: "Not Found" } } : route(body);
      return { ok: reply.status >= 200 && reply.status < 300, status: reply.status, json: async () => reply.body };
    }),
  );
  return sent;
}

export function answer(body: unknown, status = 200): Route {
  const route: Route = () => ({ status, body });
  return route;
}
