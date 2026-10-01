"""CPU benchmark of the processor hot path (parse -> normalise -> VIN check -> Bloom dedup -> rules), no I/O.

Shows per-core throughput; the pipeline scales out by Kafka partitions (one consumer per partition).
"""
import json
import random
import time

from fleetpulse.core.normalise import normalise
from fleetpulse.core.streaming import BloomFilter, ReorderBuffer
from fleetpulse.core.vin import is_valid_vin
from fleetpulse.processor.rules import RuleEngine
from fleetpulse.simulator.run import Fleet, make_payload

N = 200_000
fleet, rnd = Fleet(100_000), random.Random(1)
raw = [json.dumps(make_payload(fleet, i % fleet.n, rnd, 1790000000.0 + i / 1000)).encode() for i in range(N)]
bloom, order, rules = BloomFilter(5_000_000), ReorderBuffer(), RuleEngine()
t0 = time.perf_counter()
alerts = 0
for b in raw:
    e = normalise(json.loads(b))
    if not is_valid_vin(e.vin) or bloom.add(f"{e.vin}:{e.seq}"):
        continue
    order.observe(e.vin, e.seq)
    alerts += len(rules.evaluate(e))
dt = time.perf_counter() - t0
print(f"events={N} seconds={dt:.2f} events_per_sec_per_core={N / dt:.0f} alerts={alerts}")
