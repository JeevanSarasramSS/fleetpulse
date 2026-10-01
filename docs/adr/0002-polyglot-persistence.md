# ADR-0002: Polyglot persistence: Postgres (3NF + partitioned telemetry + pgvector) and Redis

**Context.** Two very different workloads: high-rate append-only telemetry with time-range scans, and strongly
consistent business data (tenants, users, subscriptions, alerts, work orders, audit). Plus semantic retrieval for
the copilot and sub-millisecond "where is every vehicle now" reads.

**Options.** Single Postgres for everything; Cassandra/Scylla for telemetry; ClickHouse for analytics;
Redis for hot state; a dedicated vector DB (Qdrant).

**Decision.**
- **Postgres (CP)** for the 3NF core, and **telemetry range-partitioned by hour** (retention = DROP PARTITION,
  per-partition `(vin, ts)` index, unique `(vin, seq, ts)` for idempotent writes, a default partition so a stray
  late event never blocks the stream). The `vehicle_daily` table is the warm-tier rollup the batch model reads; it is
  maintained incrementally from a watermark (each raw row counted exactly once), so raw partitions can be dropped
  after `TELEMETRY_RETENTION_HOURS` while 7-day features survive.
- *Revised during hardening:* a first version used a materialised view refreshed every minute. It re-scanned all
  raw telemetry each run, so batch time and disk grew without bound (~5 GB/hour at 5K events/s). The incremental
  rollup keeps batch cost flat and lets hot-tier retention be hours instead of days.
- **Redis (AP, NoSQL key-value + geo index)** for latest vehicle state, live map (`GEOSEARCH`), rate limiting,
  pub/sub alert fan-out and a 2 s response cache.
- **pgvector (HNSW)** inside Postgres for the fault knowledge base: one fewer system to run, transactional with the data it describes.

**Consequences.** Fewer moving parts for the hackathon; a proven path to move raw telemetry to ClickHouse or
Scylla (and Parquet on S3 for cold) when a single Postgres primary hits its write ceiling (~50-100K rows/s with
batching). The processor writes through one repository function, so that swap is contained.
