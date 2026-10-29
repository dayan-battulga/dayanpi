"""The one background-loop shape the app's workers share: start, tick on an interval, stop."""

import logging
import threading
import time

logger = logging.getLogger(__name__)

STOP_JOIN_TIMEOUT_S = 3.0
TICK_ERROR_LOG_EVERY = 100  # consecutive failures between tracebacks, so a broken tick can't flood the journal


class LoopThread:
    """Subclasses implement tick() (and before_loop() if needed). A tick that raises is logged, not fatal."""

    def __init__(self, name: str, interval_s: float) -> None:
        self._name = name
        self._interval_s = interval_s
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.tick_failures = 0

    @property
    def running(self) -> bool:
        alive = self._thread is not None and self._thread.is_alive()
        return alive

    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name=self._name, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=STOP_JOIN_TIMEOUT_S)
            self._thread = None

    def before_loop(self) -> None:
        """Runs once on the thread before the first tick."""

    def tick(self) -> None:
        raise NotImplementedError

    def _loop(self) -> None:
        try:
            self.before_loop()
        except Exception:
            logger.exception("%s: setup failed, running anyway", self._name)
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.tick()
                self.tick_failures = 0
            except Exception:
                self.tick_failures += 1
                if self.tick_failures == 1 or self.tick_failures % TICK_ERROR_LOG_EVERY == 0:
                    logger.exception("%s: tick failed (%s in a row)", self._name, self.tick_failures)
            self._stop.wait(max(0.0, self._interval_s - (time.monotonic() - started)))
