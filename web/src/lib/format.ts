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

export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, "0");
  const text = hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${minutes}:${secs}`;
  return text;
}

export function formatDate(epochSeconds: number): string {
  const day = new Date(epochSeconds * 1000).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  const text = `${day} · ${formatTimeOfDay(epochSeconds)}`;
  return text;
}

export function formatUptime(seconds: number): string {
  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const text = `${days}d ${hours}h ${minutes}m`;
  return text;
}

export function formatBits(kbps: number): string {
  const text = kbps >= 1000 ? `${(kbps / 1000).toFixed(1)} Mb/s` : `${Math.round(kbps)} kb/s`;
  return text;
}
