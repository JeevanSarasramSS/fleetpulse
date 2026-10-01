# ADR-0002: Polyglot persistence: Postgres (3NF + partitioned telemetry + pgvector) and Redis

**Context.** Two very different workloads: high-rate append-only telemetry with time-range scans, and strongly
consistent business data (tenants, users, subscriptions, alerts, work orders, audit). Plus semantic retrieval for
the copilot and sub-millisecond "where is every vehicle now" reads.

**Options.** Single Postgres for everything; Cassandra/Scylla for telemetry; ClickHouse for analytics;
Redis for hot state; a dedicated vector DB (Qdrant).

**Decision.**
- **Postgres (CP)** for the 3NF core, and **telemetry range-partitioned by day** (retention = DROP PARTITION,
  per-partition `(vin, ts)` index, unique `(vin, seq, ts)` for idempotent writes). A materialised view
  `vehicle_daily` is the warm-tier rollup the batch model reads.
- **Redis (AP, NoSQL key-value + geo index)** for latest vehicle state, live map (`GEOSEARCH`), rate limiting,
  pub/sub alert fan-out and a 2 s response cache.
- **pgvector (HNSW)** inside Postgres for the fault knowledge base: one fewer system to run, transactional with the data it describes.

**Consequences.** Fewer moving parts for the hackathon; a proven path to move raw telemetry to ClickHouse or
Scylla (and Parquet on S3 for cold) when a single Postgres primary hits its write ceiling (~50-100K rows/s with
batching). The processor writes through one repository function, so that swap is contained.
