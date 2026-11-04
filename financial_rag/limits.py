"""Process-local limits for the local demo; not a distributed deployment limiter."""

import threading
import time
from collections import defaultdict, deque


class Limits:
    def __init__(self):
        self.events = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, identity, kind="ask", now=None):
        now = time.time() if now is None else now
        with self.lock:
            queue = self.events[(identity, kind)]
            while queue and queue[0] <= now - 86400:
                queue.popleft()
            hourly = sum(t > now - 3600 for t in queue)
            if hourly >= (6 if kind == "ingest" else 30) or len(queue) >= (
                40 if kind == "ingest" else 600
            ):
                return False
            queue.append(now)
            return True
