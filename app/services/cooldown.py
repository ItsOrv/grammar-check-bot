import time


class Cooldown:
    """Per (chat, user) cooldown so one user isn't corrected repeatedly."""

    def __init__(self, seconds: int):
        self.seconds = seconds
        self._last: dict[tuple[int, int], float] = {}

    def is_active(self, chat_id: int, user_id: int) -> bool:
        last = self._last.get((chat_id, user_id))
        return last is not None and (time.monotonic() - last) < self.seconds

    def mark(self, chat_id: int, user_id: int) -> None:
        self._last[(chat_id, user_id)] = time.monotonic()
        # Keep the map from growing forever in busy groups.
        if len(self._last) > 10_000:
            cutoff = time.monotonic() - self.seconds
            self._last = {k: v for k, v in self._last.items() if v >= cutoff}
