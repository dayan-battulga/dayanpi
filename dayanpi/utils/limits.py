"""The limits' shared parts, in memory like the sign-in waits: a token bucket, and a journal line a minute at most for
whatever a limit turns away, so a flood never floods the journal too."""

import threading
from collections import Counter

NOTE_EVERY_S = 60.0


class TokenBucket:
    """rate a second in the long run, burst at once. Thread-safe.
    ponytail: in memory, so a restart refills every bucket."""

    def __init__(self, rate: float, burst: float) -> None:
        self._rate = rate
        self._burst = burst
        self._tokens = burst
        self._at: float | None = None
        self._lock = threading.Lock()

    def take(self, now: float) -> float:
        """0 when it took one; otherwise the seconds until one will be there, and nothing is taken."""
        with self._lock:
            waited = 0.0 if self._at is None else max(0.0, now - self._at)
            self._tokens = min(self._burst, self._tokens + waited * self._rate)
            self._at = now
            wait = 0.0 if self._tokens >= 1.0 else (1.0 - self._tokens) / self._rate
            if wait == 0.0:
                self._tokens -= 1.0
        return wait


class RefusalNote:
    """Counts what a limit turned away, by key, and says when the next journal line is due: at the first one, then
    at most once every NOTE_EVERY_S, however many come in between."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._said_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def count(self, key: str, now: float) -> int:
        """One more for key. The number turned away since the last line when a line is due, else 0."""
        with self._lock:
            self._counts[key] += 1
            said = self._said_at.get(key)
            due = said is None or now - said >= NOTE_EVERY_S
            counted = self._counts.pop(key) if due else 0
            if due:
                self._said_at[key] = now
        return counted
