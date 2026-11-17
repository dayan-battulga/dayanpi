import { useEffect, useState } from "react";

export const PHONE_QUERY = "(max-width: 639px)";
// From here up, who's here is the sidebar; between this and a phone it's the bottom bar (SPEC's widths).
export const WIDE_QUERY = "(min-width: 1280px)";

// Whether a media query matches right now, following it as the window changes.
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const follow = () => setMatches(media.matches);
    follow();
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, [query]);
  return matches;
}
