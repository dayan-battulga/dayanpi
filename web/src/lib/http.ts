import { loadPage } from "@/lib/navigation";

export type Method = "GET" | "POST" | "PATCH" | "DELETE";

export interface Reply<T> {
  ok: boolean;
  status: number; // 0 when the request never got an answer
  body: T | null; // only on a 2xx
  detail: string | null; // FastAPI's {"detail": ...} on an error, readable
  retryAfterS: number | null; // a 429's Retry-After: how long the sign-in's wait has left
}

// These two answer 401 for a wrong password or a bad invite, not for a missing session.
const SIGN_IN_PATHS = new Set(["/api/login", "/api/join"]);

// "next" can only send you somewhere on this site. Checking the raw string isn't enough: the URL parser drops
// tabs and newlines and reads \ as /, so "/\t/evil.example" becomes //evil.example. Resolve it the way the
// browser will and keep it only when it stays on this origin. The path it hands back is checked too: "/.//evil.example"
// stays here, but its pathname comes out as //evil.example, which location.assign reads as another host.
export function readSafeNext(next: string | null): string {
  let safe = "/";
  try {
    const url = new URL(next ?? "", window.location.origin);
    if (next?.startsWith("/") && url.origin === window.location.origin && !/^\/[/\\]/.test(url.pathname)) {
      safe = url.pathname + url.search + url.hash;
    }
  } catch {
    // Not a URL at all (like "//["): stay on "/".
  }
  return safe;
}

export function sendToLogin(): void {
  const here = window.location.pathname + window.location.search;
  loadPage(`/login?next=${encodeURIComponent(here)}`);
}

// A string, or 422's list of {loc, msg}: the first one, with the field it's about. Pydantic puts
// "Value error, " in front of a message the Pi's own validators raise.
function readDetail(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail;
  const first = Array.isArray(detail) ? (detail[0] as { loc?: unknown[]; msg?: string } | undefined) : undefined;
  let text: string | null = typeof detail === "string" ? detail : null;
  if (first?.msg != null) {
    const field = String(first.loc?.at(-1) ?? "").replace(/_/g, " ");
    const message = first.msg.replace(/^Value error, /, "");
    text = field ? `${field}: ${message}` : message;
  }
  return text;
}

// Every request on the page goes through here. Writes always send a JSON body ("{}" when there's
// nothing to say), because the Pi refuses any other write; a 401 means signing in again.
export async function request<T>(method: Method, path: string, body?: object): Promise<Reply<T>> {
  let reply: Reply<T> = { ok: false, status: 0, body: null, detail: null, retryAfterS: null };
  const write = method === "GET" ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) };
  try {
    const response = await fetch(path, { method, cache: "no-store", ...write });
    const parsed: unknown = await response.json().catch(() => null);
    const retryAfter = response.status === 429 ? Number(response.headers.get("Retry-After")) : NaN;
    reply = {
      ok: response.ok,
      status: response.status,
      body: response.ok ? (parsed as T) : null,
      detail: response.ok ? null : readDetail(parsed),
      retryAfterS: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
    };
    if (response.status === 401 && !SIGN_IN_PATHS.has(path)) {
      sendToLogin();
    }
  } catch {
    // Offline, or the Pi is restarting: the caller sees status 0.
  }
  return reply;
}

export async function fetchJson<T>(path: string): Promise<T | null> {
  const reply = await request<T>("GET", path);
  return reply.body;
}
