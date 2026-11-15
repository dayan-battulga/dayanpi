export type FeedState = "off" | "connecting" | "live" | "retrying";

export function describeFeeds(states: FeedState[]): string {
  const on = states.filter((state) => state !== "off");
  let text = "hidden · nothing saved";
  if (on.includes("retrying")) {
    text = "reconnecting…";
  } else if (on.includes("connecting")) {
    text = "connecting…";
  } else if (on.length > 0) {
    text = "live · nothing saved";
  }
  return text;
}
