# STRIDE threat model (ingestion path + public API)

| # | Threat (STRIDE) | Where | Control in FleetPulse | Status |
|---|---|---|---|---|
| 1 | **Spoofing** a vehicle to inject fake faults | Device → broker | mTLS per-device certs at the MQTT/Kafka edge (production); VIN check-digit validation + unknown-VIN DLQ in processor | VIN/DLQ done; mTLS planned |
| 2 | **Tampering** / replaying events to flood alerts | Kafka → processor | Bloom-filter + unique `(vin, seq, ts)` dedup; alert `dedup_key`; per-VIN sequence tracking | Done |
| 3 | **Repudiation** of approvals or data access | API, copilot | Append-only `audit_log` (trigger blocks UPDATE/DELETE) on every read of vehicle detail, ack, approve, erase, login and agent tool call | Done |
| 4 | **Information disclosure** across tenants / of driver location | API | JWT tenant claim on every query; 404 (not 403) for other tenants' VINs; analysts get geohash-5 masked locations; WebSocket channel per tenant | Done |
| 5 | **Denial of service** via bursts or API abuse | Ingest, API | Kafka buffering + producer back-pressure; per-user Redis rate limit (429 + Retry-After); bounded per-VIN state in rule engine; HPA | Done |
| 6 | **Elevation of privilege** via prompt injection | Copilot | Injection screen, tenant-scoped tools only, no write tools except "propose", human approval, grounding check, tool budget | Done |

Secrets: env/K8s Secret synced from Vault or cloud secret manager; `.env.example` only in git. TLS 1.3 terminates at
ingress; RDS/ElastiCache/MSK encrypted at rest (AES-256 KMS) and in transit (Terraform). Passwords: PBKDF2-SHA256, 200K iterations.
