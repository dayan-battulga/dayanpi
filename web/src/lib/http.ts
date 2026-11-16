export async function fetchJson<T>(path: string): Promise<T | null> {
  let reply: T | null = null;
  try {
    const response = await fetch(path);
    reply = response.ok ? ((await response.json()) as T) : null;
  } catch {
    reply = null;
  }
  return reply;
}
