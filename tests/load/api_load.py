"""Async API load test across the main read endpoints; prints throughput and p50/p95/p99.

usage: python api_load.py BASE_URL REQUESTS CONCURRENCY [CLIENT_PROCESSES]

One Python asyncio client tops out around 300-400 req/s, so the load is split over several client processes
(default 4) and their latencies merged; otherwise the test measures the client, not the API. Run it inside the
compose network (http://api:8000) on Windows/macOS: Docker Desktop's port proxy adds its own queueing.
"""
import asyncio
import multiprocessing as mp
import statistics
import sys
import time

import httpx

PATHS = ["/api/v1/alerts?limit=50", "/api/v1/vehicles?limit=50", "/api/v1/risk?limit=25", "/api/v1/stats"]


def client(base: str, n: int, c: int, offset: int, out):
    async def run():
        async with httpx.AsyncClient(base_url=base, timeout=10, limits=httpx.Limits(max_connections=c)) as cl:
            tok = (await cl.post("/api/v1/auth/token", json={"email": "manager@aurora.demo", "password": "demo1234"})).json()
            h = {"Authorization": f"Bearer {tok['access_token']}"}
            lat, codes, sem = [], {}, asyncio.Semaphore(c)

            async def one(i):
                async with sem:
                    t = time.perf_counter()
                    r = await cl.get(PATHS[(i + offset) % len(PATHS)], headers=h)
                    lat.append((time.perf_counter() - t) * 1000)
                    codes[r.status_code] = codes.get(r.status_code, 0) + 1

            await asyncio.gather(*(one(i) for i in range(n)))
            return lat, codes
    out.put(asyncio.run(run()))


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
    c = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    procs = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    q = mp.Queue()
    workers = [mp.Process(target=client, args=(base, n // procs, max(1, c // procs), i, q)) for i in range(procs)]
    t0 = time.perf_counter()
    for w in workers:
        w.start()
    results = [q.get() for _ in workers]
    for w in workers:
        w.join()
    dt = time.perf_counter() - t0
    lat = [x for r in results for x in r[0]]
    codes = {}
    for r in results:
        for k, v in r[1].items():
            codes[k] = codes.get(k, 0) + v
    p = statistics.quantiles(lat, n=100)
    print(f"requests={len(lat)} concurrency={c} clients={procs} rps={len(lat) / dt:.0f} "
          f"p50={p[49]:.1f}ms p95={p[94]:.1f}ms p99={p[98]:.1f}ms codes={codes}")


if __name__ == "__main__":
    main()
