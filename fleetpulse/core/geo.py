"""Geo algorithms: haversine, geohash, Dijkstra to nearest service depot, DP trip segmentation."""
import heapq
import math

_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def geohash(lat: float, lon: float, precision: int = 6) -> str:
    """Encode to geohash. O(precision)."""
    lat_r, lon_r, out, bits, ch, even = [-90.0, 90.0], [-180.0, 180.0], [], 0, 0, True
    while len(out) < precision:
        rng, val = (lon_r, lon) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            ch = (ch << 1) | 1
            rng[0] = mid
        else:
            ch <<= 1
            rng[1] = mid
        even, bits = not even, bits + 1
        if bits == 5:
            out.append(_B32[ch])
            bits, ch = 0, 0
    return "".join(out)


def dijkstra(graph: dict, src, targets: set, max_cost: float = math.inf):
    """Nearest target reachable within max_cost (e.g. remaining range km).

    graph: node -> list[(neighbour, cost)]. O((V + E) log V) time, O(V) space.
    Returns (target, cost, path) or None.
    """
    dist, prev, pq = {src: 0.0}, {}, [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, math.inf):
            continue
        if d > max_cost:
            return None
        if u in targets:
            path = [u]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            return u, d, path[::-1]
        for v, w in graph.get(u, ()):
            nd = d + w
            if nd < dist.get(v, math.inf):
                dist[v], prev[v] = nd, u
                heapq.heappush(pq, (nd, v))
    return None


def segment_trips(speeds: list[float], stop_cost: float = 1.0, switch_penalty: float = 2.5):
    """Label each GPS sample as moving(1) / stopped(0) with a 2-state DP (Viterbi-style).

    Noisy speed readings are smoothed by penalising state switches, so a single
    zero-speed blip mid-trip does not split a trip. O(n) time, O(n) space.
    Returns (labels, trips) where trips are (start_idx, end_idx) inclusive.
    """
    n = len(speeds)
    if n == 0:
        return [], []

    def cost(state, v):  # emission cost
        return (v / 5.0) * stop_cost if state == 0 else max(0.0, (5.0 - v) / 5.0) * stop_cost

    dp = [[0.0, 0.0] for _ in range(n)]
    bt = [[0, 0] for _ in range(n)]
    dp[0] = [cost(0, speeds[0]), cost(1, speeds[0])]
    for i in range(1, n):
        for s in (0, 1):
            stay, swap = dp[i - 1][s], dp[i - 1][1 - s] + switch_penalty
            dp[i][s], bt[i][s] = (stay, s) if stay <= swap else (swap, 1 - s)
            dp[i][s] += cost(s, speeds[i])
    s = 0 if dp[-1][0] <= dp[-1][1] else 1
    labels = [0] * n
    for i in range(n - 1, -1, -1):
        labels[i] = s
        s = bt[i][s]
    trips, start = [], None
    for i, lab in enumerate(labels):
        if lab == 1 and start is None:
            start = i
        if lab == 0 and start is not None:
            trips.append((start, i - 1))
            start = None
    if start is not None:
        trips.append((start, n - 1))
    return labels, trips
