const STORAGE_PREFIX = "dayanpi.";

// Private windows and blocked site data throw on localStorage; the fallback is fine then.
export function readStored(key: string, fallback: string | null): string | null {
  let value = fallback;
  try {
    value = window.localStorage.getItem(STORAGE_PREFIX + key) ?? fallback;
  } catch {
    value = fallback;
  }
  return value;
}

export function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + key, value);
  } catch {
    // Not remembered this time; the page still works.
  }
}
