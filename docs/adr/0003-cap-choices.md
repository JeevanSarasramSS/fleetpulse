# ADR-0003: CAP / PACELC choice per data class

| Data | Store | Choice | Why |
|---|---|---|---|
| Tenants, users, roles, subscriptions, work orders, audit log | Postgres primary + sync standby | **CP**, PC/EC | Wrong ownership or a lost approval/audit row is worse than a few seconds of unavailability. |
| Alerts | Postgres, unique `dedup_key` | **CP** writes, idempotent | Retries and replays must never create duplicate alerts. |
| Raw telemetry | Kafka (RF=3, acks=all) then partitioned Postgres | **AP**, PA/EL | Keep ingesting during partitions; eventual consistency of a 1 Hz signal is fine; dedup on read path. |
| Live vehicle state, geo index, rate-limit counters, stats cache | Redis | **AP**, PA/EL | Freshness and latency over strictness; rebuilt from the stream if lost; limiter fails open. |

**Delivery semantics.** Device→Kafka is at-least-once (duplicates simulated at 1%). Kafka→sinks is at-least-once
with manual offset commit *after* the DB transaction; sinks are idempotent (`ON CONFLICT DO NOTHING`), giving
effectively-once results without Kafka transactions.
