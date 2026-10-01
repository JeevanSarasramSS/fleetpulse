"""Streaming data structures used on the hot path."""
import hashlib
import math
from collections import deque


def _hashes(key: str, k: int, m: int):
    # Kirsch-Mitzenmacher double hashing: k hashes from two 64-bit halves
    d = hashlib.blake2b(key.encode(), digest_size=16).digest()
    h1, h2 = int.from_bytes(d[:8], "little"), int.from_bytes(d[8:], "little")
    return [(h1 + i * h2) % m for i in range(k)]


class BloomFilter:
    """Probabilistic set for duplicate detection. Insert/query O(k), space O(m) bits."""

    def __init__(self, capacity: int, error_rate: float = 0.001):
        self.m = max(8, int(-capacity * math.log(error_rate) / (math.log(2) ** 2)))
        self.k = max(1, round(self.m / capacity * math.log(2)))
        self.bits = bytearray((self.m + 7) // 8)
        self.count = 0

    def add(self, key: str) -> bool:
        """Add key; return True if it was (probably) already present."""
        present = True
        for h in _hashes(key, self.k, self.m):
            byte, bit = divmod(h, 8)
            if not self.bits[byte] & (1 << bit):
                present = False
                self.bits[byte] |= 1 << bit
        if not present:
            self.count += 1
        return present

    def __contains__(self, key: str) -> bool:
        return all(self.bits[h // 8] & (1 << (h % 8)) for h in _hashes(key, self.k, self.m))


class CountMinSketch:
    """Frequency estimation for top-K fault codes. Update/query O(d), space O(w*d)."""

    def __init__(self, width: int = 2048, depth: int = 4):
        self.w, self.d = width, depth
        self.table = [[0] * width for _ in range(depth)]

    def add(self, key: str, n: int = 1):
        for row, h in enumerate(_hashes(key, self.d, self.w)):
            self.table[row][h] += n

    def estimate(self, key: str) -> int:
        return min(self.table[row][h] for row, h in enumerate(_hashes(key, self.d, self.w)))


class TopK:
    """Heavy hitters: CMS for counts plus a bounded candidate dict. O(d + log k) per update."""

    def __init__(self, k: int = 10):
        self.k, self.cms, self.cands = k, CountMinSketch(), {}

    def add(self, key: str):
        self.cms.add(key)
        self.cands[key] = self.cms.estimate(key)
        if len(self.cands) > self.k * 4:
            keep = sorted(self.cands.items(), key=lambda kv: -kv[1])[: self.k * 2]
            self.cands = dict(keep)

    def top(self):
        return sorted(self.cands.items(), key=lambda kv: -kv[1])[: self.k]


class SlidingWindow:
    """Time-based sliding window mean/max. Amortised O(1) per event (monotonic deque for max)."""

    def __init__(self, seconds: float):
        self.span, self.q, self.maxq, self.total = seconds, deque(), deque(), 0.0

    def add(self, ts: float, value: float):
        self.q.append((ts, value))
        self.total += value
        while self.maxq and self.maxq[-1][1] <= value:
            self.maxq.pop()
        self.maxq.append((ts, value))
        self._evict(ts)

    def _evict(self, now: float):
        while self.q and self.q[0][0] < now - self.span:
            self.total -= self.q.popleft()[1]
        while self.maxq and self.maxq[0][0] < now - self.span:
            self.maxq.popleft()

    @property
    def mean(self):
        return self.total / len(self.q) if self.q else 0.0

    @property
    def max(self):
        return self.maxq[0][1] if self.maxq else 0.0


class ReorderBuffer:
    """Per-vehicle sequence tracker: flags late (out-of-order) events. O(1)."""

    def __init__(self):
        self.last_seq: dict[str, int] = {}

    def observe(self, vin: str, seq: int) -> bool:
        """Return True if event is in order, False if it arrived late."""
        prev = self.last_seq.get(vin, -1)
        if seq > prev:
            self.last_seq[vin] = seq
            return True
        return False
