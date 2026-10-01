"""Stream processor: Kafka -> normalise -> validate -> dedup -> rules -> Postgres/Redis.

Delivery: at-least-once from Kafka (manual commit after sinks succeed) + idempotent sinks
(telemetry unique (vin, seq, ts), alert dedup_key) = effectively-once results.
"""
import json
import signal
import time
from datetime import datetime, timezone

import psycopg
import redis
from confluent_kafka import Consumer, Producer
from prometheus_client import Counter, Histogram, start_http_server

from .. import config
from ..core.normalise import UnknownFormat, normalise
from ..core.streaming import BloomFilter, ReorderBuffer, TopK
from ..core.vin import is_valid_vin
from .rules import RuleEngine

EVENTS = Counter("fp_events_total", "Events consumed", ["outcome"])
LATENCY = Histogram("fp_ingest_latency_seconds", "Vehicle timestamp -> processed",
                    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10))
ALERTS = Counter("fp_alerts_total", "Alerts raised", ["rule"])
BATCH = Histogram("fp_batch_seconds", "Batch processing time")

INSERT_TELEMETRY = """
INSERT INTO telemetry (vin, ts, seq, lat, lon, speed_kmh, odo_km, soc_pct, fuel_pct, coolant_c, batt_v, evt, dtcs)
SELECT vin, ts, seq, lat, lon, speed_kmh, odo_km, soc_pct, fuel_pct, coolant_c, batt_v, evt,
       CASE WHEN dtcs_csv = '' THEN NULL ELSE string_to_array(dtcs_csv, ',') END
FROM unnest(%s::char(17)[], %s::timestamptz[], %s::bigint[], %s::real[], %s::real[], %s::real[], %s::real[],
            %s::real[], %s::real[], %s::real[], %s::real[], %s::text[], %s::text[])
  AS t(vin, ts, seq, lat, lon, speed_kmh, odo_km, soc_pct, fuel_pct, coolant_c, batt_v, evt, dtcs_csv)
ON CONFLICT DO NOTHING
"""

INSERT_ALERT = """
INSERT INTO alert (tenant_id, vin, rule, severity, detail, event_ts, dedup_key)
VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (dedup_key) DO NOTHING RETURNING alert_id, created_at
"""


class Processor:
    def __init__(self):
        self.pg = psycopg.connect(config.PG_DSN, autocommit=False)
        self.r = redis.Redis.from_url(config.REDIS_URL)
        with self.pg.cursor() as c:
            c.execute("SELECT v.vin, f.tenant_id FROM vehicle v JOIN fleet f USING (fleet_id)")
            self.tenant_of = {vin: t for vin, t in c.fetchall()}
        self.pg.commit()
        self.bloom = BloomFilter(5_000_000, 0.001)
        self.order = ReorderBuffer()
        self.rules = RuleEngine()
        self.topk = TopK(10)
        self.dlq = Producer({"bootstrap.servers": config.KAFKA_BOOTSTRAP})
        self.consumer = Consumer({"bootstrap.servers": config.KAFKA_BOOTSTRAP, "group.id": "processor",
                                  "enable.auto.commit": False, "auto.offset.reset": "earliest",
                                  "max.poll.interval.ms": 300000,
                                  # a killed replica is evicted from the group in ~10 s (default 45 s), so the
                                  # survivors get its partitions back quickly after a crash
                                  "session.timeout.ms": 10000, "heartbeat.interval.ms": 3000})
        self.consumer.subscribe([config.TOPIC_RAW])
        self.running = True

    def to_dlq(self, raw: bytes, reason: str):
        self.dlq.produce(config.TOPIC_DLQ, raw, headers={"reason": reason[:200]})
        EVENTS.labels("dlq").inc()

    def handle_batch(self, msgs):
        rows = [[] for _ in range(13)]
        latest, alerts, now = {}, [], time.time()
        for m in msgs:
            if m.error():
                continue
            raw = m.value()
            try:
                e = normalise(json.loads(raw))
            except (UnknownFormat, ValueError, KeyError, TypeError) as ex:
                self.to_dlq(raw, f"schema:{ex}")
                continue
            if not is_valid_vin(e.vin) or e.vin not in self.tenant_of:
                self.to_dlq(raw, "invalid_or_unknown_vin")
                continue
            if self.bloom.add(f"{e.vin}:{e.seq}"):
                EVENTS.labels("duplicate").inc()
                continue
            in_order = self.order.observe(e.vin, e.seq)
            EVENTS.labels("ok" if in_order else "late").inc()
            LATENCY.observe(max(0.0, now - e.ts_ms / 1000))
            for col, val in zip(rows, (e.vin, datetime.fromtimestamp(e.ts_ms / 1000, timezone.utc), e.seq, e.lat, e.lon,
                                       e.speed_kmh, e.odo_km, e.soc_pct, e.fuel_pct, e.coolant_c, e.batt_v, e.evt,
                                       ",".join(e.dtcs))):
                col.append(val)
            for code in e.dtcs:
                self.topk.add(code)
            if in_order:  # never let a late event overwrite newer live state
                latest[e.vin] = e
            alerts.extend(self.rules.evaluate(e))

        # Alerts first, in their own small transaction, and pushed before the bulk telemetry insert so a
        # critical fault never waits behind ~thousands of telemetry rows. Replays are safe: dedup_key makes
        # the insert a no-op, so an alert is never pushed twice.
        new_alerts = []
        if alerts:
            with self.pg.cursor() as c:
                for a in alerts:
                    c.execute(INSERT_ALERT, (self.tenant_of[a.vin], a.vin, a.rule, a.severity, json.dumps(a.detail),
                                             datetime.fromtimestamp(a.event_ts_ms / 1000, timezone.utc), a.dedup_key))
                    got = c.fetchone()
                    if got:
                        new_alerts.append((got[0], a))
            self.pg.commit()
        if new_alerts:
            p = self.r.pipeline(transaction=False)
            for alert_id, a in new_alerts:
                ALERTS.labels(a.rule).inc()
                p.publish(f"alerts:{self.tenant_of[a.vin]}", json.dumps(
                    {"alert_id": alert_id, "vin": a.vin, "rule": a.rule, "severity": a.severity, "detail": a.detail,
                     "event_ts_ms": a.event_ts_ms, "processed_ms": int(time.time() * 1000)}))
            p.execute()

        if rows[0]:
            with self.pg.cursor() as c:
                c.execute(INSERT_TELEMETRY, rows)
            self.pg.commit()

        p = self.r.pipeline(transaction=False)
        for vin, e in latest.items():
            t = self.tenant_of[vin]
            p.hset(f"v:{vin}", mapping={k: ("" if v is None else (",".join(v) if isinstance(v, list) else v))
                                        for k, v in e.to_dict().items()})
            p.geoadd(f"geo:{t}", (e.lon, e.lat, vin))
        n_ok = len(rows[0])
        p.incrby("stats:events", n_ok)
        sec = f"stats:eps:{int(time.time())}"  # per-second bucket shared by all replicas (fleet-wide events/s)
        p.incrby(sec, n_ok)
        p.expire(sec, 15)
        p.set("stats:topdtc", json.dumps(self.topk.top()))
        if latest:  # data freshness: how old the newest state we just made readable is (vehicle clock -> Redis)
            ages = sorted(time.time() * 1000 - e.ts_ms for e in latest.values())
            p.set("stats:fresh_ms", round(ages[len(ages) // 2]), ex=30)
        p.execute()
        self.consumer.commit(asynchronous=False)  # commit only after sinks succeeded
        return n_ok

    def run(self):
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "running", False))
        last, count = time.time(), 0
        while self.running:
            # Small, frequent batches: consume() waits for the full timeout unless num_messages arrive, so a
            # long timeout adds straight to alert latency. 0.1 s keeps p50 well under a second.
            msgs = self.consumer.consume(num_messages=2000, timeout=0.1)
            if not msgs:
                continue
            with BATCH.time():
                count += self.handle_batch(msgs)
            self.dlq.poll(0)
            if time.time() - last >= 5:
                eps = count / (time.time() - last)
                print(f"processed {eps:.0f} events/s", flush=True)
                last, count = time.time(), 0
        self.consumer.close()


if __name__ == "__main__":
    start_http_server(9100)
    for i in range(60):
        try:
            Processor().run()
            break
        except psycopg.OperationalError as ex:
            print("waiting for postgres:", ex, flush=True)
            time.sleep(2)
