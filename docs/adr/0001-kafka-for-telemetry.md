# ADR-0001: Kafka (Redpanda locally) as the telemetry backbone

**Context.** 100K vehicles at 1 Hz = 100K events/s with 3x bursts; consumers (stream processor, sinks, future ML
feature jobs) must replay history after bugs or outages and scale out independently.

**Options.** RabbitMQ (queues, no replay, per-message acks limit throughput); MQTT broker only (no durable
partitioned log); Kafka / Redpanda (partitioned, replicated, replayable log).

**Decision.** Kafka protocol. Topic `telemetry.raw`, 12 partitions locally (sized to 48+ in production), key = VIN so
each vehicle's events stay ordered on one partition and one consumer. Redpanda in docker compose (single binary,
Kafka API compatible); MSK / Confluent / Event Hubs in cloud, selected by `KAFKA_BOOTSTRAP` only.
Bad payloads go to `telemetry.dlq` with a reason header instead of blocking the partition.

**Consequences.** Replay and horizontal scale by adding partitions/consumers with no code change. Ordering is only
per VIN, so late events are detected per vehicle (ReorderBuffer). Operating Kafka is heavier than a queue, accepted.
