"""Fill the hackathon Solution Document template with FleetPulse content. Usage: python fill_template.py template.docx out.docx"""
import copy
import pathlib
import sys

import docx
from docx.shared import Inches
from docx.text.paragraph import Paragraph
from docx.table import Table

REPO = "https://github.com/JeevanSarasramSS/fleetpulse"
ROOT = pathlib.Path(__file__).resolve().parents[2].as_posix()  # repo root, any OS

COVER = {
    "To be Submitted by:": "To be Submitted by: Jeevan Sarasram S S (solo entry)",
    "Team Members & Roles:": "Team Members & Roles: Jeevan Sarasram S S (Reg. No. RA2311056010035), solo developer: problem framing, architecture, backend, data engineering, ML, DevOps and testing; js9882@srmist.edu.in, jeevansiva2005@gmail.com",
    "Problem Space Chosen:": "Problem Space Chosen: Predictive maintenance for mixed ICE / hybrid / EV fleets (with real-time critical-fault alerting)",
    "Repository URL:": f"Repository URL: {REPO} (tag v1.0-submission)",
    "Demo Video URL": "Demo Video URL (≤ 5 min): [Link]",
    "Date of Submission:": "Date of Submission: 01/10/2026",
}

# Each answer: list of items; str = paragraph, ("img", path, width_in), ("b", text) = bold-lead paragraph, ("table", header, rows)
A = {}
A["1. Executive Summary"] = [
    ("b", "Problem. ", "Unplanned breakdowns are the most expensive event in a commercial fleet: a tow, an emergency repair and two days of a vehicle earning nothing. Fleet managers running mixed petrol, hybrid and EV fleets see fault codes and warning lights only after the fact, scattered across OEM portals with different formats."),
    ("b", "Solution. ", "FleetPulse streams telemetry from every vehicle, raises critical faults on the manager's screen within seconds, and every minute ranks the whole fleet by its probability of breaking down in the next 7 days, with the reasons and a dollar estimate. A fleet copilot answers questions over the same data and proposes work orders that a human approves."),
    ("b", "Results (measured on the submitted code). ", "100,000 simulated vehicles across 3 tenants and 2 OEM payload formats; ~5,000 events/s sustained end to end with 3x bursts every two minutes on four processor replicas (CPU hot path 33.9K events/s per core); critical alert vehicle → screen p50 0.17 s and p95 2.6 s even through a 3x burst (target < 5 s); 100,000 vehicles scored in ~10 s; risk model ROC-AUC 0.878 vs 0.688 for the mileage-since-service baseline and 4.2x the baseline's precision on the top 2% of the fleet; API p95 71 ms at 10 concurrent users; slowest query 174 ms → 0.58 ms; recovery from killing both processors and restarting the broker with zero data loss."),
    ("b", "What is distinctive. ", "Effectively-once processing without Kafka transactions (at-least-once + idempotent sinks); explainable per-vehicle risk factors; a copilot with propose-only tools, tenant-scoped data access, injection screening, VIN grounding checks and an append-only audit trail; and honest gap reporting (section 12)."),
]
A["2.1 Problem Statement"] = [
    "“A fleet manager needs a way to know which vehicles will fail in the next week and act before they do, because breakdowns are discovered only when a driver is stranded, which today costs roughly US$2,400 per incident in towing, emergency repair and two days of lost vehicle utilisation (our working assumption, see 2.2).”",
    ("b", "Primary user: ", "Fleet manager of a commercial or rental fleet (1,000–100,000 vehicles, mixed ICE / hybrid / EV)."),
    ("b", "Secondary stakeholders: ", "drivers (safety, fewer roadside failures), maintenance workshops (planned rather than emergency work), fleet finance (cost and utilisation), OEMs (warranty and fault-pattern insight), lenders and insurers (asset condition)."),
]
A["2.2 Evidence & Validation"] = [
    "Facts are taken from the brief and public sources; numbers we could not verify are marked as assumptions and are the inputs to our savings estimate, so they can be changed in one place (fleetpulse/agent/copilot.py).",
    "Validation method: a simulation in which every vehicle has a hidden wear state that drives observable symptoms (coolant temperature, 12 V voltage, fault-code rate) and a breakdown hazard. The model is trained and back-tested on 100,000 simulated vehicle-weeks, and the same simulator feeds the live system.",
    "Existing alternatives: aftermarket OBD dongles (hardware cost and install, one data format); OEM portals (one brand per portal, alerts after the fault); rule-only telematics (alerts on a code, no ranking of who fails next); Motorq Fuse (AI recommendations on OEM data, commercial). FleetPulse combines device-free multi-OEM ingestion, sub-5-second alerts and an explainable 7-day forecast in one view.",
]
A["2.3 Impact & Success Metrics"] = [
    ("b", "Scale of impact: ", "With a 2.8% weekly breakdown base rate in the simulation, a 10K-vehicle fleet sees ~280 breakdowns a week and a 100K fleet ~2,800. Servicing the 50 highest-risk vehicles of one 33K-vehicle tenant avoids an expected 31 breakdowns this week: US$74.5K avoided against US$11.4K planned spend, net US$63K per week (live copilot estimate from the running system)."),
    ("b", "Wider impact: ", "safety (critical faults such as HV-isolation and coolant over-temperature are surfaced in seconds), cost (planned repairs instead of tows), environment (misfire and catalyst faults fixed earlier cut emissions), compliance (audit trail, masked location for analysts, erasure flow)."),
]
A["3.1 Solution Overview & User Journey"] = [
    "FleetPulse is a web dashboard backed by a streaming pipeline. Vehicles (here, the simulator) stream telemetry; FleetPulse normalises every OEM format into one event, detects faults in real time, scores every vehicle's 7-day breakdown risk each minute, and lets a fleet manager act from one screen.",
    "User journey: (1) a Borealis van reports coolant at 119 °C and code P0217 in OEM-specific JSON; (2) the processor normalises it, validates the VIN check digit, drops duplicates and evaluates sliding-window rules; (3) an OVERHEAT_TREND / CRITICAL_DTC alert is written idempotently and pushed over WebSocket, appearing on the dashboard ~0.2 s after the vehicle timestamp; (4) the manager opens the vehicle: 73% 7-day risk, reasons “overdue for service, coolant running hot, 12 V battery voltage low”, the coolant trend and recent alerts; (5) they click Propose work order (or ask the copilot); (6) the work order appears as proposed and a manager approves it; every step is in the audit log.",
    ("img", "docs/evidence/dashboard.png", 6.3),
    ("img", "docs/evidence/vehicle_drawer.png", 6.3),
]
A["3.2 Key Value Proposition"] = [
    ("b", "Customer job: ", "keep every vehicle earning by fixing problems before they strand a driver."),
    ("b", "Pain relieved: ", "no more discovering failures from the roadside; one place for all OEMs; no manual triage of thousands of fault codes."),
    ("b", "Gain created: ", "a ranked, explained list of who will fail this week, a dollar figure for acting now, and a copilot that turns a question into a proposed work order."),
    ("b", "Differentiation: ", "device-free and multi-OEM by design (adapter per OEM), explainable ML that beats the mileage rule fleets use today by 4.2x on the top of the list, and AI that can only propose, never act, with a full audit trail."),
]
A["3.3 Innovative Ideas"] = [
    ("b", "1. Effectively-once without distributed transactions. ", "At-least-once Kafka consumption with offsets committed only after the database transaction, plus idempotent sinks (unique (vin, seq, ts) on telemetry, a deterministic dedup_key per vehicle/rule/code/hour on alerts) and a Bloom filter fast path. Evidence: 1% duplicate and 2% out-of-order events are injected continuously; killing both processors and restarting the broker produced no duplicate alerts and the backlog drained at ~9K events/s."),
    ("b", "2. Symptom-to-hazard simulation as a validation harness. ", "The simulator gives each vehicle a hidden wear level that drives both noisy symptoms and the breakdown hazard, so the model must infer wear from symptoms, as in reality. This lets us measure model lift against the industry rule (service overdue) honestly: ROC-AUC 0.878 vs 0.688."),
    ("b", "3. Propose-only, grounded copilot. ", "Tools are tenant-scoped SQL, the only write tool creates a 'proposed' work order, every VIN in an answer must come from a tool result (otherwise the answer is withheld), injection attempts are refused, and every tool call is audited. It runs deterministically offline and uses Claude tool-use when a key is configured."),
]
A["5.1 Architecture Overview"] = [
    ("b", "System context (C4 L1): ", "users (fleet manager, analyst, admin) use the FleetPulse web app; FleetPulse ingests from OEM clouds/vehicles (simulated), optionally calls an LLM API (Anthropic) for copilot planning, and would authenticate through an OIDC provider in production."),
    ("b", "Container view (C4 L2) and data flow: ", "see diagram. One telemetry event: vehicle → Kafka (~20 ms producer linger) → processor batch (0.1–0.2 s; alerts are written and pushed before the bulk telemetry upsert) → Redis pub/sub → WebSocket (< 50 ms) → screen. Measured p50 0.17 s, p95 2.6 s vehicle timestamp to screen across a 3x burst."),
    ("img", "docs/diagrams/arch.png", 6.5),
]
A["5.4 Deployment View"] = [
    "Kubernetes namespace fleetpulse (pod-security restricted): api Deployment (3 replicas, HPA 3–20 on CPU, PDB minAvailable 2, zone topology spread), processor Deployment (6 replicas ≤ partitions; KEDA on consumer lag in production), risk-scoring CronJob every 5 minutes, default-deny NetworkPolicy, TLS Ingress via cert-manager. Containers run as non-root with read-only root filesystems and dropped capabilities. Secrets come from a K8s Secret synced from Vault / cloud secret manager (infra/k8s/fleetpulse.yaml).",
    "Cloud-agnostic approach: the application only reads KAFKA_BOOTSTRAP, PG_DSN, REDIS_URL and JWT_SECRET from the environment (12-factor). Terraform for AWS (infra/terraform/aws: VPC, EKS, MSK, RDS Multi-AZ, ElastiCache, all encrypted) provisions the backing services; the same manifests run on GKE/AKS with Confluent/Event Hubs, Cloud SQL/Flexible Server and Memorystore/Azure Cache, or locally on kind/k3d and docker compose, with no code change.",
]
A["6.4 Interfaces, Contracts & Runtime Flows"] = [
    ("b", "API contract: ", "OpenAPI 3 generated by FastAPI at /openapi.json (Swagger UI at /docs). Versioned under /api/v1. Keyset (cursor) pagination with opaque base64 cursors on vehicles and alerts. Errors are RFC 7807 application/problem+json. Rate limit 600 requests/min per user, HTTP 429 with Retry-After. WebSocket /ws/alerts?token=… streams tenant-scoped alerts."),
    ("b", "Event schemas: ", "topic telemetry.raw (12 partitions, key = VIN, retention 24 h); telemetry.dlq (reason header); alerts. Payloads are JSON in two OEM shapes (Aurora: flat ISO-time metric; Borealis: nested epoch imperial with a raw fault string), mapped to one CanonicalEvent dataclass. Evolution: a new OEM or version is a new adapter class registered in ADAPTERS; unknown shapes go to the DLQ rather than blocking a partition. Avro/Protobuf with a schema registry is the production next step."),
    ("b", "Flow 1 (happy path, critical fault): ", "simulator.produce(key=VIN) → processor.consume(batch≤5000) → normalise → is_valid_vin → bloom.add(vin:seq) → ReorderBuffer.observe → RuleEngine.evaluate → INSERT telemetry … ON CONFLICT DO NOTHING; INSERT alert … ON CONFLICT (dedup_key) DO NOTHING RETURNING → Redis HSET/GEOADD/PUBLISH → commit offsets → API WebSocket → dashboard."),
    ("b", "Flow 2 (failure: duplicate + broker down): ", "the device retries an event (duplicate) → Bloom filter drops it; if the Bloom state was lost in a crash, the unique index and dedup_key absorb the replay. If the broker is down, the producer buffers and applies back-pressure (BufferError → poll and retry); processors block on consume and resume from the last committed offset. Measured: processors killed and broker restarted at 13:02:10, consumption resumed and drained the backlog at ~9K events/s against ~5.9K/s input."),
]
A["6.5 Algorithms & Data Structures"] = [
    ("table", ["Problem", "Algorithm / structure", "Complexity", "Scale tested"], [
        ["VIN validation", "Regex ^[A-HJ-NPR-Z0-9]{17}$ + ISO 3779 weighted check digit (mod 11)", "O(17) time, O(1) space", "100K generated VINs; 500 random round-trips in tests"],
        ["DTC parsing from raw OEM strings", "Regex \\b([PCBU])([0-3])([0-9A-F])([0-9A-F]{2})\\b with de-duplication", "O(n) in payload length", "every event (~6K/s)"],
        ["Duplicate detection", "Bloom filter, k hashes by double hashing (blake2b), m = −n ln p / (ln 2)²", "O(k) per op, ~9 MB for 5M keys at p=0.001", "5M capacity per processor"],
        ["Top-K fault codes", "Count-Min Sketch (w=2048, d=4) + bounded candidate set", "O(d + K log K) per update", "live stream, shown in /stats"],
        ["Overheat and harsh-brake patterns", "Time-based sliding window with monotonic deque for max", "amortised O(1) per event", "100K vehicles, bounded state"],
        ["Late events", "Per-VIN last-sequence map (never overwrite newer live state)", "O(1)", "2% out-of-order injected"],
        ["Trip segmentation of noisy speed", "2-state DP (Viterbi-style) with switch penalty", "O(n) time and space", "unit-tested; blips do not split trips"],
        ["Nearest reachable depot / charger", "Dijkstra with binary heap and range cut-off", "O((V+E) log V)", "unit-tested"],
        ["Live map", "Geohash (base32) and Redis GEO index (geohash-ordered sorted set)", "O(log n + m)", "4,000 vehicles per map refresh"],
        ["Pagination", "Keyset on primary key", "O(log n) per page at any depth", "100K vehicles"],
    ]),
    "Pseudocode (processor batch): for m in batch: e ← adapter(m); if !valid(e.vin) → DLQ; if bloom.add(e.vin:e.seq) → skip; inOrder ← order.observe(e); rows += e; alerts += rules(e); if inOrder: latest[e.vin] ← e. Then one transaction: upsert rows, insert alerts RETURNING new; then Redis pipeline; then commit offsets.",
    "Measured: hot path (parse → normalise → VIN → Bloom → rules) 200,000 events in 5.90 s = 33.9K events/s on one core (tests/load/processor_bench.py).",
]
A["7. Non-Functional Requirements & Performance Benchmarks"] = [
    "Load test setup: everything on one 4-vCPU cloud VM under docker compose (Redpanda, Postgres 16, Redis, 2 processors, simulator, batch, API) with 100K vehicles at a 5,000 events/s base rate and 3x bursts for 10 s every 2 minutes. API load: tests/load/api_load.py (async httpx) against 4 uvicorn workers, rate limiter raised for the test. Processor CPU benchmark: tests/load/processor_bench.py. Alert latency was re-measured after hardening on a 16-vCPU laptop with 4 processor replicas (docs/evidence/alert_latency.txt). Raw outputs in docs/evidence/.",
    "Results: API 2,000 requests at 10 concurrent: 326 rps, p50 25 ms, p95 71 ms, p99 110 ms (all 200). At 50 concurrent on the same shared box: p95 456 ms, p99 576 ms: the CPU is shared with the pipeline, and the fix is horizontal (API HPA, read replicas). Processor ~2.5K events/s per replica including Postgres writes; consumer lag drained after chaos at ~9K events/s.",
]
A["8. Security & Compliance"] = [
    ("table", ["#", "STRIDE threat", "Control", "Status"], [
        ["1", "Spoofing a vehicle", "VIN check digit + unknown-VIN DLQ; per-device mTLS at the edge", "Done / mTLS planned"],
        ["2", "Tampering / replay flooding alerts", "Bloom + unique (vin, seq, ts); alert dedup_key; per-VIN sequence", "Done"],
        ["3", "Repudiation of approvals / access", "Append-only audit_log (DB trigger) on reads, acks, approvals, erasure, logins, agent tools", "Done"],
        ["4", "Cross-tenant disclosure", "Tenant claim in JWT applied to every query; 404 for foreign VINs; tenant pub/sub channels", "Done"],
        ["5", "DoS via bursts / API abuse", "Kafka buffering, producer back-pressure, Redis rate limit (429), bounded rule state, HPA", "Done"],
        ["6", "Privilege escalation via prompt injection", "Injection screen, scoped tools, propose-only writes, human approval, grounding", "Done"],
    ]),
    ("b", "AuthN/AuthZ: ", "JWT (HS256, 2 h expiry, issuer check) issued after PBKDF2-SHA256 (200K iterations) password verification; RBAC roles admin / fleet_manager / analyst enforced per endpoint; tenant isolation on every query. Production design: OIDC (Keycloak or cloud IdP) issuing RS256 tokens, same claims."),
    ("b", "Device identity & encryption: ", "designed for per-device X.509 mTLS at the MQTT/Kafka edge; TLS 1.3 at ingress (cert-manager); RDS, ElastiCache and MSK encrypted at rest (AES-256 KMS) and in transit (Terraform); secrets via K8s Secret synced from Vault; .env.example only in git. Security headers (nosniff, frame deny, no-referrer, no-store) on every response."),
    ("b", "Privacy (GDPR, DPDP Act 2023): ", "analysts see only geohash-5 (~5 km) masked positions; driver PII lives in one table and is erased by DELETE /api/v1/drivers/{id} (PII nulled, operational rows kept, audit row written); telemetry retention is a partition drop (24 h in Kafka, 7–90 days warm, then cold); Mumbai region for Indian data residency."),
    ("b", "AI safety: ", "see section 11."),
]
A["10. Observability"] = [
    "Every service exposes Prometheus metrics: fp_events_total{outcome=ok|late|duplicate|dlq}, fp_ingest_latency_seconds (vehicle timestamp → processed), fp_alerts_total{rule}, fp_batch_seconds, fp_api_latency_seconds{route}. docker compose --profile observability starts Prometheus and Grafana. Consumer lag comes from rpk group describe / the Kafka exporter. Logs are structured stdout collected by the platform (Loki/ELK). The dashboard itself shows live events/s and measured alert latency.",
    "Troubleshooting a latency spike: (1) Grafana: is fp_api_latency p95 up for one route or all? (2) If all, check pod CPU and the Postgres connection pool; if one route, run EXPLAIN ANALYZE on its query (as in 5.3). (3) For alert latency, compare fp_ingest_latency with consumer lag: rising lag means processors are saturated, so scale replicas up to the partition count; flat lag but slow batches (fp_batch_seconds) points to Postgres writes. (4) Correlate with simulator burst logs. OpenTelemetry tracing across services is the next step.",
]
A["11. AI / ML Component (if used)"] = [
    ("b", "Purpose: ", "rank every vehicle by its probability of breaking down in the next 7 days. Rules alone catch faults that have already happened; the model combines weak, noisy signals (slowly rising coolant, sagging 12 V voltage, an uptick in minor codes, overdue service) into an early warning."),
    ("b", "Data and features: ", "100,000 simulated vehicle-weeks from the same wear model as the live simulator; features: service-overdue ratio, age, odometer, max coolant (7 d), min 12 V (7 d), fault-code events (7 d), harsh brakes (7 d), EV / hybrid flags. Live features come from the vehicle_daily rollup, which the batch job maintains incrementally (only rows since the last watermark are read, each counted exactly once). Leakage check: the label is drawn from a hazard on the hidden wear, which is never a feature; only noisy symptoms are."),
    ("b", "Model: ", "scikit-learn HistGradientBoostingClassifier (200 iterations); per-vehicle explanations from importance-weighted deviation from the fleet median. Vector store: pgvector HNSW over a fault/repair knowledge base, embedded with a dependency-free hashed n-gram embedding so it runs offline."),
    ("table", ["Metric (held-out 25%)", "Model", "Baseline: km since service", "Lift"], [
        ["ROC-AUC", "0.878", "0.688", "+0.19"], ["PR-AUC", "0.190", "0.054", "3.5x"], ["Precision @ top 2%", "27.8%", "6.6%", "4.2x"]]),
    ("b", "Agent: ", "six tools (top_risk, vehicle_summary, open_alerts, search_knowledge, estimate_savings, propose_work_order), all filtered by the caller's tenant. Planner: Claude tool-use if ANTHROPIC_API_KEY is set, else a deterministic intent router. Guardrails: injection screen, max 6 tool calls, VIN grounding check, propose-only actions requiring human approval, every tool call audited as agent:<user>. Cost/latency: deterministic mode ~20–40 ms and US$0; LLM mode is a few model calls per question."),
]
A["12. Architecture Decisions, Risks & Future Enhancements"] = [
    ("b", "ADRs (docs/adr): ", "0001 Kafka as telemetry backbone (replay, per-VIN ordering, DLQ); 0002 polyglot persistence (Postgres 3NF + day-partitioned telemetry + pgvector, Redis for hot state); 0003 CAP/PACELC per data class and effectively-once delivery; 0004 single Python image with batch hot path and a deterministic-first copilot."),
    ("b", "Risks and shortcuts: ", "100K events/s not proven end to end (measured 5K/s on 4 vCPUs; ~34K/s per core CPU path implies 4–6 processor replicas plus a telemetry store beyond a single Postgres primary). mTLS, OIDC and Vault are designed, not running. The model is validated on simulated data only. Terraform is unapplied. Bloom state is per process and lost on restart (DB constraints keep correctness)."),
    ("b", "Next three steps to pilot: ", "(1) move raw telemetry to ClickHouse or Scylla with Parquet cold storage and run a 100K events/s k6/Kafka load test on EKS; (2) Avro + schema registry and mTLS device identity; (3) retrain on a real pilot fleet's maintenance history and add survival-analysis time-to-failure."),
]
A["15. Conclusion"] = [
    "Key learnings: idempotent sinks make at-least-once delivery safe and are far simpler than distributed transactions; partitioning by time turns retention into a metadata operation, but only if the rollups are incremental (our first materialised-view version re-scanned all history every minute and grew ~5 GB/hour until we replaced it); most API latency wins came from indexes that match the query's filter and order.",
    "Strengths: a working end-to-end system on 100,000 vehicles with measured numbers, an ML model that clearly beats the status-quo rule, and security and compliance built into the data model rather than added on.",
    "Challenges solved: duplicate and out-of-order events, two incompatible OEM formats, per-tenant isolation from the database to the WebSocket, and recovery after killing processors and the broker.",
]
A["16. Declarations"] = [
    ("b", "Open-source components: ", "FastAPI (MIT), Uvicorn (BSD), Pydantic (MIT), psycopg 3 (LGPL), redis-py (MIT), confluent-kafka / librdkafka (Apache-2.0 / BSD), scikit-learn (BSD), NumPy (BSD), joblib (BSD), PyJWT (MIT), prometheus-client (Apache-2.0), anthropic SDK (MIT), Leaflet (BSD-2), pytest-bdd (MIT), Esri World Dark Gray Canvas map tiles (Esri terms, attributed in the UI), PostgreSQL (PostgreSQL licence), pgvector (PostgreSQL licence), Redis 7 (BSD), Redpanda (BSL, dev only), Prometheus and Grafana (Apache-2.0 / AGPL)."),
    ("b", "AI tools used: ", "Claude (Anthropic) via Claude Code was used to plan, write and test code, generate diagrams and draft this document; the team reviewed and owns the result. The running copilot can optionally call the Anthropic Messages API."),
    ("b", "Data: ", "all vehicles, VINs, drivers, positions and fault histories are synthetic and generated by our simulator; no real personal or vehicle-owner data is used."),
]
A["17. Appendix (if any)"] = [
    "Evidence files in the repository: docs/evidence/api_load.txt, processor_bench.txt, explain_analyze.txt, chaos.txt, dashboard.png, vehicle_drawer.png; fleetpulse/ml/metrics.json; docs/threat-model.md; docs/adr/*.md; docs/demo-script.md.",
    ("img", "docs/diagrams/er.png", 6.5),
    "References: Connected Vehicle Intelligence Hackathon problem statement (Talenciaglobal, 2026); SAE J2012 (DTC definitions); ISO 3779 / NHTSA 49 CFR 565 (VIN check digit); Kafka documentation (idempotent producer, consumer groups); PostgreSQL 16 declarative partitioning; pgvector HNSW.",
]

TABLES = {
    "Evidence / Assumption": [
        ["Unplanned breakdowns cost far more than planned repairs (tow, emergency labour, downtime)", "Industry fleet-maintenance literature; our assumption US$2,400 vs US$650", "Size of the pain per incident", "Medium"],
        ["Connected cars will generate up to ~25 GB/hour; ~95% of new cars connected by 2030", "Problem statement (McKinsey / S&P)", "Data volume requires stream processing, not batch exports", "High"],
        ["Rising coolant temperature and falling 12 V voltage precede failures by days", "Simulation (hidden-wear model) and common maintenance practice", "Symptoms carry a learnable early signal", "Medium"],
        ["Mileage-since-service rule is the common baseline today", "Assumption from OEM service schedules", "Baseline the model must beat", "Medium"],
        ["Our model ranks risk 4.2x better than the rule at the top 2%", "Back-test on 25,000 held-out simulated vehicles", "Where to send scarce workshop capacity", "High (on simulated data)"],
    ],
    "Metric": [
        ["Critical fault to manager's screen", "Hours to days (driver call)", "< 5 s", "Measured p50 0.17 s, p95 2.6 s via WebSocket timestamps"],
        ["Precision of 'service now' list (top 2%)", "6.6% (mileage rule)", "> 20%", "Back-test: 27.8%"],
        ["Unplanned breakdowns / 1,000 vehicles / week", "28 (simulated base rate)", "−30%", "Estimated: servicing top-50 avoids ~31 of the tenant's expected breakdowns"],
        ["Net weekly saving, one 33K-vehicle tenant", "US$0", "> US$50K", "Copilot estimate: US$63K net"],
    ],
    "ID": [
        ["F-01", "Multi-OEM telemetry ingestion and normalisation", "As a platform team I want new OEM formats handled by an adapter so that onboarding needs no downtime", "Must", "Done", "fleetpulse/core/normalise.py", "[mm:ss]"],
        ["F-02", "100K-vehicle simulator with bursts, duplicates, late events", "As an engineer I want realistic load so that we can prove scale", "Must", "Done", "fleetpulse/simulator/", "[mm:ss]"],
        ["F-03", "Real-time critical fault alerts (< 5 s)", "As a fleet manager I want critical faults instantly so that drivers are not stranded", "Must", "Done", "fleetpulse/processor/", "[mm:ss]"],
        ["F-04", "7-day breakdown risk ranking with reasons", "As a fleet manager I want to know who will fail this week and why so that I book them in", "Must", "Done", "fleetpulse/ml/", "[mm:ss]"],
        ["F-05", "Live fleet map", "As a dispatcher I want to see where vehicles are so that I can route recovery", "Should", "Done", "web/index.html, /api/v1/live", "[mm:ss]"],
        ["F-06", "Fleet copilot with work-order proposals", "As a fleet manager I want to ask questions in plain English and get actions I approve", "Should", "Done", "fleetpulse/agent/", "[mm:ss]"],
        ["F-07", "RBAC, tenant isolation, location masking", "As an admin I want analysts to see only coarse locations of our own fleet", "Must", "Done", "fleetpulse/api/, core/security.py", "[mm:ss]"],
        ["F-08", "Audit log and right-to-erasure", "As a DPO I want every access logged and driver PII erasable", "Must", "Done", "db/001_schema.sql, DELETE /drivers", "[mm:ss]"],
        ["F-09", "Savings estimate", "As finance I want the dollar impact of acting now", "Could", "Done", "copilot.estimate_savings", "[mm:ss]"],
        ["F-10", "OIDC SSO and device mTLS", "As security I want federated login and device identity", "Should", "Planned", "docs/threat-model.md", "–"],
        ["F-11", "ClickHouse/Parquet cold tier", "As a platform team I want cheap years of history", "Could", "Planned", "ADR-0002", "–"],
    ],
    "Layer": None,  # handled specially (two different tables start with 'Layer')
    "Query": [
        ["Vehicle detail: last 30 min of telemetry for one VIN (3M rows)", "174", "0.58", "Composite index (vin, ts DESC) per daily partition + partition pruning on ts"],
        ["Top-25 risk for a tenant (100K scores)", "27.3", "0.40", "Index (tenant_id, score DESC) → index scan with LIMIT, no sort"],
        ["Open alerts feed, keyset page", "2.7", "0.15", "Partial index WHERE acked_at IS NULL + keyset on alert_id instead of OFFSET"],
    ],
    "Pattern": [
        ["Adapter", "Maps each OEM's payload format to one canonical event", "fleetpulse/core/normalise.py (AuroraAdapter, BorealisAdapter)"],
        ["Repository / ports", "Keeps SQL out of domain logic; rules and algorithms are pure and unit-tested", "fleetpulse/processor/rules.py (pure) vs processor/run.py (I/O)"],
        ["Idempotent consumer", "At-least-once delivery without duplicate rows or alerts", "processor/run.py, unique keys in db/001_schema.sql"],
        ["CQRS (lite)", "Writes go through Kafka/processor; reads from Redis hot state, the incremental vehicle_daily rollup and the risk table", "processor/, ml/score.py, api/main.py"],
        ["Strategy", "Copilot planner: LLM tool-use or deterministic router behind one interface", "fleetpulse/agent/copilot.py"],
        ["Observer / pub-sub", "Alerts fan out to WebSocket clients per tenant", "Redis PUBLISH in processor, /ws/alerts in API"],
        ["Graceful degradation", "Rate limiter fails open; map falls back from Esri to OpenStreetMap tiles and works without any tile CDN; pollers survive API restarts; copilot falls back from LLM", "api/deps.py, web/index.html, agent/copilot.py"],
    ],
    "NFR": [
        ["Ingest Throughput", "100K+ events/sec", "~5K/s sustained on 4 vCPUs (2 replicas); 33.9K/s per core CPU path", "Simulator + processor logs; processor_bench.py"],
        ["End-to-End Latency", "< 2 s dashboard; < 5 s critical alert", "Critical alert p50 0.17 s, p95 2.6 s, max 3.2 s through a 3x burst; dashboard KPIs refresh every 3 s", "WebSocket push timestamp minus vehicle timestamp"],
        ["API Latency", "p95 < 200 ms; p99 < 500 ms", "p95 71 ms, p99 110 ms @10 conc.; p95 456 ms @50 conc. on shared box", "tests/load/api_load.py"],
        ["Resilience", "Recovers after broker / pod failure", "Recovered: processors killed + broker restarted, backlog drained at ~9K/s, no duplicates", "docs/evidence/chaos.txt"],
        ["Availability", "99.9%, no single point of failure", "Design: 3 API replicas + PDB, RF=3 brokers, Multi-AZ RDS, Redis failover; not measured", "infra/k8s, infra/terraform"],
    ],
    "Test Type": [
        ["Unit", "pytest, pytest-cov", "50", "99% line coverage on core, rules, guardrails, features", "Yes"],
        ["Integration & Contract", "pytest + httpx against docker compose; consumer-driven contracts (dashboard as consumer) verified against the live API and its OpenAPI", "8 + 10", "auth, tenant isolation, RBAC, masking, pagination, erasure, guardrail, response contracts: all pass", "Yes (e2e job)"],
        ["Acceptance (BDD)", "pytest-bdd Gherkin features (tests/acceptance/features)", "6 scenarios", "risk list, alert ack + audit, copilot work order + human approval, analyst masking, tenant isolation, erasure: all pass", "Yes (e2e job)"],
        ["Performance / Load / Soak", "api_load.py, processor_bench.py, 15+ min continuous run", "3", "p95 71 ms @10; 33.9K ev/s/core; ~5.4M events over the soak", "Partial"],
        ["Security (SAST, DAST, Dependency, Image)", "Semgrep, Bandit, pip-audit, Trivy, OWASP ZAP baseline", "5", "Bandit clean (0 medium/high); ZAP and Trivy reports in the CI run", "Yes"],
        ["Compliance & Chaos", "erasure + audit test; kill processors + restart broker", "2", "Audit row on erase; recovery with no data loss", "Yes"],
    ],
    "Time": None,
}
DEMO = [["0:00 – 0:30", "Problem", "Stranded van, US$2,400 per breakdown, 2,800 breakdowns/week at 100K vehicles"],
        ["0:30 – 1:00", "Solution", "“FleetPulse tells you who breaks down this week, why, and what it saves”"],
        ["1:00 – 3:00", "Live Demo", "Login, live KPIs, critical alert arriving, open vehicle (73% risk + reasons), copilot questions, propose and approve work order, analyst login shows masked map"],
        ["3:00 – 4:15", "Under the Hood", "Architecture slide, docker compose ps, kill processors and broker live, lag drains; query plans; model vs baseline"],
        ["4:15 – 5:00", "Impact & Next Steps", "US$63K/week net for one tenant, 4.2x precision, honest gaps, roadmap, team"]]
STACK = [["Ingestion / Messaging", "Kafka protocol (Redpanda locally, MSK/Confluent in cloud), key = VIN", "Replay, partitioned per-vehicle ordering, consumer groups; RabbitMQ rejected (no replay, lower throughput)"],
         ["Stream / Batch Processing", "Python consumer with batch upserts; batch scorer + incremental rollup", "Simple, testable and measured at 34K ev/s/core; Flink/Spark rejected as too heavy for the time box (next step at scale)"],
         ["Relational / NoSQL / Cache / Search / Vector", "PostgreSQL 16 (3NF + partitions) · Redis 7 · pgvector HNSW", "ACID core and analytics in one engine; Redis for sub-ms live state/geo; pgvector avoids another system. ClickHouse/Scylla deferred (ADR-0002)"],
         ["Backend / Frontend", "FastAPI (async, OpenAPI) · single-page HTML/JS + Leaflet", "Fast to build, typed contracts; no front-end build step; React rejected for time"],
         ["ML / AI", "scikit-learn HistGradientBoosting · Claude tool-use (optional)", "Strong tabular baseline with explanations; LLM only plans tool calls, never owns facts"],
         ["Infrastructure / CI-CD / Observability", "Docker compose, Kubernetes manifests, Terraform (AWS), GitHub Actions, Prometheus + Grafana", "Portable across clouds by configuration; CI runs lint, unit tests with coverage gate, SAST, e2e (integration, contract, BDD), ZAP DAST, image scan and chaos"]]
LAYERS = [["Presentation / API", "fleetpulse/api: HTTP, WebSocket, validation (Pydantic), auth, RBAC, DTO mapping", "Contain business rules"],
          ["Application / Service", "processor/run.py, ml/score.py, agent/copilot.py: use cases, transactions, orchestration", "Depend on a specific OEM format"],
          ["Domain", "fleetpulse/core + processor/rules.py: canonical event, VIN/DTC rules, algorithms, alert rules (pure Python, no I/O)", "Import framework or infrastructure code"],
          ["Infrastructure", "api/deps.py, Kafka/Postgres/Redis clients, SQL", "Leak vendor types into the domain"]]

PRINCIPLES = {
    "SOLID:": "SOLID: single responsibility per module (normalise, rules, streaming structures); open/closed for OEMs (add an adapter, touch nothing else); dependency inversion in the copilot (planner strategy over the same tools).",
    "12-Factor App:": "12-Factor App: all config from environment (fleetpulse/config.py); stateless API and processors (state in Kafka offsets, Postgres, Redis); disposable containers with SIGTERM handling; one image, many process types.",
    "Idempotency, Fail-Fast": "Idempotency, Fail-Fast, Least Privilege, DRY, KISS: idempotent sinks and alert dedup keys; schema and VIN validation fail fast into the DLQ; non-root read-only containers and role-scoped endpoints; shared feature code for training and scoring (DRY); one Python image instead of five stacks (KISS).",
}


def para_after(anchor, text="", style=None):
    new = copy.deepcopy(anchor._p)
    for r in list(new):
        if r.tag.endswith("}r") or r.tag.endswith("}hyperlink"):
            new.remove(r)
    anchor._p.addnext(new)
    p = Paragraph(new, anchor._parent)
    if style:
        p.style = style
    if text:
        p.add_run(text)
    return p


def fill_table(t: Table, rows):
    tmpl_row = t.rows[1]._tr if len(t.rows) > 1 else None
    for r in list(t.rows)[1:]:
        t._tbl.remove(r._tr)
    for vals in rows:
        tr = copy.deepcopy(tmpl_row)
        t._tbl.append(tr)
        row = t.rows[-1]
        for cell, v in zip(row.cells, vals):
            for p in cell.paragraphs[1:]:
                p._p.getparent().remove(p._p)
            p = cell.paragraphs[0]
            for r in list(p.runs):
                r._r.getparent().remove(r._r)
            p.add_run(str(v))


_BASE = {}


def new_table_after(doc, anchor, header, rows):
    """Clone a 4-column table from the template so new tables share its styling."""
    tbl = copy.deepcopy(_BASE["t"])
    anchor._p.addnext(tbl)
    t = Table(tbl, anchor._parent)
    for cell, h in zip(t.rows[0].cells, header):
        runs = cell.paragraphs[0].runs
        runs[0].text = h
        for r in runs[1:]:
            r._r.getparent().remove(r._r)
    fill_table(t, rows)
    return t


def write_items(doc, placeholder: Paragraph, items):
    cur = placeholder
    first = True
    for it in items:
        if isinstance(it, str):
            p = placeholder if first else para_after(cur)
            if first:
                for r in list(p.runs):
                    r._r.getparent().remove(r._r)
            p.add_run(it)
            cur = p
        elif it[0] == "b":
            p = placeholder if first else para_after(cur)
            if first:
                for r in list(p.runs):
                    r._r.getparent().remove(r._r)
            p.add_run(it[1]).bold = True
            p.add_run(it[2])
            cur = p
        elif it[0] == "img":
            p = para_after(cur) if not first else placeholder
            if first:
                for r in list(p.runs):
                    r._r.getparent().remove(r._r)
            p.add_run().add_picture(f"{ROOT}/{it[1]}", width=Inches(it[2]))
            cur = p
        elif it[0] == "table":
            if first:
                for r in list(placeholder.runs):
                    r._r.getparent().remove(r._r)
            t = new_table_after(doc, cur, it[1], it[2])
            cur = para_after(Paragraph(placeholder._p, placeholder._parent))  # spacer paragraph after table
            t._tbl.addnext(cur._p)
        first = False


def main(src, out):
    doc = docx.Document(src)
    body = doc.element.body
    _BASE["t"] = copy.deepcopy(next(t._tbl for t in doc.tables if t.rows[0].cells[0].text.strip() == "Evidence / Assumption"))
    # cover lines
    for p in doc.paragraphs[:12]:
        for k, v in COVER.items():
            if p.text.strip().startswith(k):
                for r in list(p.runs)[1:]:
                    r._r.getparent().remove(r._r)
                if p.runs:
                    p.runs[0].text = v
    # walk body: remember current heading, fill placeholders/tables
    heading, layer_seen = None, 0
    elements = list(body.iterchildren())
    for el in elements:
        tag = el.tag.split("}")[1]
        if tag == "p":
            p = Paragraph(el, doc._body)
            txt = p.text.strip()
            if p.style.name.startswith("Heading"):
                heading = txt
                continue
            for k, v in PRINCIPLES.items():
                if txt.startswith(k):
                    for r in list(p.runs):
                        r._r.getparent().remove(r._r)
                    p.add_run(v)
            if txt in ("[Write your answer here]", "[Insert diagrams and explanation]"):
                items = A.get(heading)
                if items:
                    write_items(doc, p, items)
            if txt.startswith("Video Link:"):
                for r in list(p.runs):
                    r._r.getparent().remove(r._r)
                p.add_run("Video Link: [URL] (script and shot list: docs/demo-script.md)")
        elif tag == "tbl":
            t = Table(el, doc._body)
            key = t.rows[0].cells[0].text.strip()
            if key == "Layer":
                layer_seen += 1
                fill_table(t, STACK if layer_seen == 1 else LAYERS)
            elif key == "Time":
                fill_table(t, DEMO)
            elif TABLES.get(key):
                fill_table(t, TABLES[key])
            # extra content right after specific tables
            if key == "Evidence / Assumption":
                pass
            if heading == "2.2 Evidence & Validation" and key == "Evidence / Assumption":
                write_items(doc, para_after(Paragraph(doc.paragraphs[0]._p, doc._body)) if False else _after_table(doc, t), A["2.2 Evidence & Validation"])
            if heading == "5.3 Data Architecture" and key == "Query":
                write_items(doc, _after_table(doc, t), [
                    ("img", "docs/diagrams/er.png", 6.5),
                    ("b", "Polyglot map: ", "Postgres 3NF core: tenants, users, subscriptions, fleets, vehicles, drivers, alerts, work orders, risk scores, audit (CP). Postgres partitioned telemetry and vehicle_daily rollup (writes buffered by Kafka, AP end to end). Redis: live state, GEO index, rate limits, pub/sub, cache (AP). pgvector: fault knowledge embeddings (CP)."),
                    ("b", "Capacity: ", "100K vehicles × 1 event/s = 100K events/s, ~0.5 KB JSON (~120 B per stored row) → 8.6 TB/day raw JSON, ~1 TB/day as rows; ~0.3 TB/day compressed in a columnar cold tier. Kafka partition key VIN (uniform hash, no hot spots); telemetry partitioned by hour with (vin, ts) indexes. Hot: Redis latest state (minutes) and raw Postgres partitions (2 h locally, configurable). Warm: Postgres/ClickHouse 90 days (~25 TB compressed at full scale). Cold: Parquet on S3 7 years (~US$0.023/GB-month → ~US$2.5K/month per PB-year)."),
                    ("b", "Denormalisation: ", "alert.tenant_id and risk_score.tenant_id duplicate fleet.tenant_id to serve the hottest tenant-filtered queries from one index; consistency is guaranteed because both are written from the same vehicle→fleet lookup."),
                ])
            if heading == "6.1 Layering & Separation of Concerns" and key == "Layer":
                write_items(doc, _after_table(doc, t), [
                    "Style: layered with ports-and-adapters at the edges. The domain (core, rules) is pure Python with no I/O, so it is unit-tested to 99% coverage and reused by the processor, the batch scorer and the API. Dependencies point inward: api → application → domain; infrastructure implements adapters (OEM adapters, Kafka, Postgres, Redis).",
                    "Folder structure: fleetpulse/{core, simulator, processor, ml, agent, api} · web/ · db/ · infra/{k8s, terraform/aws, grafana} · tests/{unit, integration, contract, acceptance, load} · docs/{adr, diagrams, evidence, solution} · .github/workflows/",
                ])
            if heading == "9. Test Strategy" and key == "Test Type":
                pass
    # test strategy bullets: append concrete answers after the guidance bullets
    for p in doc.paragraphs:
        if p.text.startswith("Report Links:"):
            write_items(doc, para_after(p, style="Normal"), [
                ("b", "Edge cases covered: ", "duplicate events, out-of-order events, unknown OEM format (DLQ), invalid VIN check digit, lowercase VINs, unknown fault codes, EVs without coolant, empty inputs, expired/tampered JWT, cross-tenant VIN access, analyst masking, prompt injection, hallucinated VINs, unbounded state under VIN floods, broker and processor failure."),
                ("b", "Sample: ", "Borealis payload {vehicleId, epoch, signals:{speedMph:10, coolantTempF:212, lvBatteryVolts:11.5}, faultString:'DTC:P0217;DTC:C0035'} → canonical {speed_kmh:16.09, coolant_c:100.0, dtcs:[P0217, C0035]} → alerts CRITICAL_DTC P0217 (sev 5), DTC C0035, LOW_12V."),
                ("b", "Reports: ", "coverage (pytest --cov, uploaded by CI), docs/evidence/api_load.txt, processor_bench.txt, explain_analyze.txt, chaos.txt; Semgrep/Bandit/pip-audit/Trivy/ZAP output and the e2e JUnit report in the GitHub Actions run."),
            ])
            break
    for p in doc.paragraphs:
        if p.text.startswith("References or external sources"):
            write_items(doc, para_after(p, style="Normal"), A["17. Appendix (if any)"])
            break
    doc.save(out)


def _after_table(doc, t):
    new = docx.oxml.OxmlElement("w:p")
    t._tbl.addnext(new)
    return Paragraph(new, doc._body)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
