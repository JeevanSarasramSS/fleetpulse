"""Async API load test: N requests at concurrency C across the main read endpoints; prints p50/p95/p99."""
import asyncio
import statistics
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
N, C = int(sys.argv[2]) if len(sys.argv) > 2 else 3000, int(sys.argv[3]) if len(sys.argv) > 3 else 50
PATHS = ["/api/v1/alerts?limit=50", "/api/v1/vehicles?limit=50", "/api/v1/risk?limit=25", "/api/v1/stats"]


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        tok = (await c.post("/api/v1/auth/token", json={"email": "manager@aurora.demo", "password": "demo1234"})).json()
        h = {"Authorization": f"Bearer {tok['access_token']}"}
        lat, codes, sem = [], {}, asyncio.Semaphore(C)

        async def one(i):
            async with sem:
                t = time.perf_counter()
                r = await c.get(PATHS[i % len(PATHS)], headers=h)
                lat.append((time.perf_counter() - t) * 1000)
                codes[r.status_code] = codes.get(r.status_code, 0) + 1

        t0 = time.perf_counter()
        await asyncio.gather(*(one(i) for i in range(N)))
        dt = time.perf_counter() - t0
    q = statistics.quantiles(lat, n=100)
    print(f"requests={N} concurrency={C} rps={N / dt:.0f} p50={q[49]:.1f}ms p95={q[94]:.1f}ms p99={q[98]:.1f}ms codes={codes}")


asyncio.run(main())
