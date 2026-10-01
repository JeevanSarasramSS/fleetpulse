# ADR-0004: Python services with batch-oriented hot path; deterministic-first copilot

**Context.** 2-hour build window; the brief rewards depth and evidence over language choice.

**Decision.** One Python codebase, one container image, five roles (api, processor, simulator, batch, seed).
The processor works in batches of up to 5,000 messages with a single `INSERT ... SELECT unnest(...)` per batch,
measured at ~34K events/s per core for the CPU path; throughput scales by partitions x replicas.
The copilot uses tenant-scoped tools, a deterministic planner by default and Claude tool-use when an API key is set,
with injection screening, VIN grounding checks, a tool-call budget, propose-only actions and an audit row per tool call.

**Consequences.** Fast delivery and one dependency tree to scan. Python per-core throughput means ~4-6 processor
replicas for 100K events/s; a Go/Rust rewrite of the processor is the first optimisation if cost matters.
