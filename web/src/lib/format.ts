export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  let text = `${total}s`;
  if (hours > 0) {
    text = `${hours}h ${String(minutes).padStart(2, "0")}m`;
  } else if (total >= 60) {
    text = `${minutes}m`;
  }
  return text;
}

export function formatTimeOfDay(epochSeconds: number): string {
  const text = new Date(epochSeconds * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }).toLowerCase();
  return text;
}

// The Desk's timer: "03:12", or "1:02:05" past an hour.
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const secs = String(total % 60).padStart(2, "0");
  const text = hours > 0 ? `${hours}:${minutes}:${secs}` : `${minutes}:${secs}`;
  return text;
}

// "Nov 15": when a token or an invite was made, or someone joined.
export function formatShortDate(epochSeconds: number): string {
  const text = new Date(epochSeconds * 1000).toLocaleDateString([], { month: "short", day: "numeric" });
  return text;
}
