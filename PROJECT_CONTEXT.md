# FleetPulse: project context and workflow

A living record of what FleetPulse is, how it is built, what has been done and what comes next.
**Update this file with every meaningful change** (add a line to the [changelog](#9-changelog) at minimum).

Deeper references, not repeated here: [README](README.md) (quick start, results) ·
[ADRs](docs/adr) (design decisions) · [threat model](docs/threat-model.md) (STRIDE) ·
[Solution Document](docs/solution/FleetPulse_Solution_Document.pdf) (the 17-section submission) ·
[demo script](docs/demo-script.md) · [evidence](docs/evidence) (load, latency, chaos, query plans).

---

## 1. What it is and why

Built for the Connected Vehicle Intelligence Hackathon (Talenciaglobal; Motorq used only as an industry reference).
The brief is open-ended in *what* to build but strict on scale, data engineering, security, testing and DevOps.

**Problem chosen: predictive maintenance for mixed ICE / hybrid / EV fleets.** FleetPulse tells a fleet manager
which vehicles will break down in the next 7 days, why, what to do and what acting now saves, and pushes critical
faults (overheating, HV isolation, brake relay) to the screen in well under a second.

Users: fleet manager (acts, approves), analyst (read-only, masked locations), admin (audit, erasure).
Three demo tenants: Aurora Logistics, Borealis Rentals, Coastal Leasing (100,000 vehicles in total).

## 2. Tech stack and why

| Layer | Choice | Why |
|---|---|---|
| Simulator | Python + NumPy (`fleetpulse/simulator`) | 100K vehicles, two OEM payload formats, bursts / duplicates / out-of-order; a hidden wear level drives both symptoms and breakdowns, so the ML problem is learnable but not trivial |
| Messaging | Kafka API via Redpanda (`telemetry.raw`, 12 partitions, key = VIN) | Durable, partitioned, replayable; Redpanda is a single light container for local runs |
| Stream processing | Python consumer group (`fleetpulse/processor`) | Normalise OEM formats, VIN check digit, Bloom-filter dedup, sliding-window rules; at-least-once + idempotent sinks = effectively-once |
| Relational | PostgreSQL 16 (3NF core, CP) | Tenants, users, fleets, vehicles, drivers, alerts, work orders, risk scores, append-only audit log |
| Telemetry | Postgres, hourly range partitions | Retention = DROP PARTITION; `(vin, ts)` indexes; ClickHouse/Scylla is the scale-out path (ADR-0002) |
| Warm tier | `vehicle_daily` incremental rollup | Batch cost stays flat as history grows; features survive raw-partition drops |
| NoSQL | Redis | Live vehicle state, GEO index for the map, rate limiting, alert pub/sub, 2 s cache |
| Vector | pgvector (HNSW) | Fault/repair knowledge base for the copilot, transactional with the data it describes |
| ML | scikit-learn gradient boosting vs mileage-since-service baseline | Explainable per-vehicle factors; evaluated against a baseline as the brief asks |
| Agent | Copilot with six tenant-scoped tools, propose-only actions | Guardrails (injection screen, grounding check), audit trail; optional LLM planner via `ANTHROPIC_API_KEY`, deterministic planner otherwise |
| API | FastAPI | JWT, RBAC, tenant isolation, keyset pagination, rate limits, RFC 7807 errors, OpenAPI |
| UI | Single-page HTML/JS + Leaflet | No build step; Esri dark canvas tiles (keyless), OpenStreetMap fallback |
| DevOps | Docker compose, K8s manifests, Terraform (AWS), GitHub Actions, Prometheus + Grafana | One-command local run; cloud-agnostic by configuration |

## 3. Architecture and data flow

```
Simulator ──Kafka (key=VIN)──► telemetry.raw ──► Processor ×4 ──┬─► Postgres: alerts (first, pushed at once)
 100K vehicles, 2 OEM formats                     normalise      ├─► Redis pub/sub ──► API WebSocket ──► dashboard
 3x bursts, dupes, late events                    VIN · dedup    ├─► Postgres: telemetry (hourly partitions)
                                                  rules          └─► Redis: live state + GEO index
Batch job (every 60 s): incremental rollup → retention (drop old partitions) → features → risk model → risk_score
API (FastAPI): REST + WebSocket, JWT/RBAC/tenant scope, audit ──► dashboard: map · alerts · 7-day risk · copilot
```

Key properties: alerts are written and pushed *before* the bulk telemetry insert; Kafka offsets are committed only
after sinks succeed; telemetry and alerts have idempotency keys, so replays never duplicate.

## 4. How to run, test and demo

```bash
docker compose up -d --build            # seeds 100K vehicles, starts the whole pipeline
open http://localhost:8000              # manager@aurora.demo / demo1234 (analyst@aurora.demo = masked view)
pip install -r requirements.txt pytest pytest-cov pytest-bdd httpx
pytest --cov                                                                # unit (99% on core)
pytest -m integration tests/integration tests/contract tests/acceptance -o addopts=""   # live stack
python tests/load/pipeline_load.py --rate 25000 --duration 120 --processors 12   # zero-loss throughput test
python tests/load/soak.py 45                                                      # soak
```

- Risk scores appear one or two batch runs (about 1-2 minutes) after a fresh start.
- Config is environment-only (`.env.example`): `EVENTS_PER_SEC`, `TELEMETRY_RETENTION_HOURS`, `RATE_LIMIT_PER_MIN`, ...
- Disk: about 5 GB per hour of raw telemetry at 5,000 events/s, capped by retention (default 2 h).
- Demo flow and timings: [docs/demo-script.md](docs/demo-script.md).

**Local machine notes (Windows):** Docker Desktop's disk image lives on `D:\DockerData` (C: filled up twice
during testing). The redis host port is 16379 to avoid clashing with other local stacks. Leave the OpenBoxLabs
containers alone; they belong to another project.

## 5. What was built, and how (timeline)

All on 2026-10-01 (IST).

| When | Milestone / decision |
|---|---|
| 19:04 | Initial system: simulator, processor, batch scorer, API, dashboard, 3NF schema, ML vs baseline, copilot, ADRs, threat model, K8s/Terraform, CI, evidence, solution document |
| 19:10-19:17 | Solution document team details + PDF; compose host-port fix; tagged `v1.0-submission` |
| 19:35 | Map showed "API key required" (CARTO tiles now need a key); switched to OpenStreetMap |
| 19:57 | Map still blocked in some browsers: the API sent `Referrer-Policy: no-referrer` and tile servers reject requests with no Referer. Fixed the header; moved to Esri dark canvas (keyless) with OSM fallback. Map now samples all depots (it used to show only the 4,000 vehicles nearest one city). Fixed CI lint (ruff) and security-scan (bandit) failures. UI polish: drawer above the map, readable risk rows, alert flash fades, pollers survive API restarts, EV-aware vehicle drawer |
| 20:02 | **Bounded telemetry.** Raw telemetry grew ~5 GB/hour with no retention, and a materialised view re-scanned all of it every minute. Replaced with hourly partitions, a default partition, `drop_old_telemetry()`, and an incremental `vehicle_daily` rollup driven by a watermark. Existing databases migrate in place (`db/002_lifecycle.sql`, applied by the batch job on start) |
| 20:07 | CI unit job had always failed on GitHub: bare `pytest` didn't put the repo root on `sys.path`. Fixed in `pyproject.toml` |
| 20:11 | **Missing test types added:** BDD acceptance (pytest-bdd, 6 scenarios), consumer-driven contract tests (10), OWASP ZAP baseline in CI; Trivy action re-pinned (old tag removed upstream) |
| 20:24 | **Alert latency.** Alerts now pushed before the telemetry insert; consume batches 0.1 s / 2,000; 4 processor replicas so capacity exceeds the 3x burst. Critical p95 7.0 s → 2.6 s. Docs, diagrams and solution document (docx + Word PDF) re-synced |
| 20:41 | **Chaos recovery.** After killing processors and restarting the broker, the consumer group stalled 2-3 min (45 s session timeout per dead member). Session timeout 10 s: flow resumes ~26 s after a broker restart. First fully green CI run (test, SAST, e2e incl. chaos) |
| 21:05 | Commit history cleaned of co-author trailers (code unchanged); `v1.0-submission` moved to `cc79ace` |
| 22:30 | Official submission format arrived (Drive folder + form, deadline Fri 2 Oct 11:00 AM); Drive-ready folder built |
| 23:00-00:30 | **Upgrade pass.** Zero-loss pipeline load test (`tests/load/pipeline_load.py`, parallel producers via `simulator --shard`): 25.7K/s offered with 3x bursts, every event written; Kafka absorbs 69K/s, Postgres ceiling ~24K/s. API: fair multi-process load client + 4 workers, p95 456 → 110 ms at 50 users. Data freshness KPI (vehicle → dashboard ~0.15 s). Fixed events/s KPI (showed one replica's share). Grafana dashboard provisioned. CI `k8s` job deploys the production manifests on kind (config-only overlay, restricted PSS); CronJob made PSS-compliant. Coverage gate widened to all domain modules (98%). Demo DB reset (old 15 GB daily partition made inserts slow). 45-min soak: 15.8M events, no restarts, freshness p50 0.19 s, but bursts back up after ~25 min. Narrated video script (later cut to ~6.5 min) |

## 6. Current status (measured)

| Area | Result | Source |
|---|---|---|
| Fleet | 100,000 vehicles, 33,333 drivers, 3 tenants, seeded in ~3.4 s | seed logs |
| Throughput | zero loss at 12.8K and 25.7K events/s offered with 3x bursts; Kafka absorbs 69K/s; ceiling ~24K/s (one Postgres); demo default 5K/s | `docs/evidence/processor_bench.txt` |
| Data freshness | vehicle → dashboard p50 ~0.15-0.19 s (target < 2 s) | dashboard KPI, `docs/evidence/soak.txt` |
| Soak (45 min) | 15.8M events, no restarts; freshness p95 7.9 s once the hourly partition outgrows cache (~25 min) | `docs/evidence/soak.txt` |
| Critical alert latency | p50 0.17 s, p95 2.6 s, max 3.2 s through a burst (target < 5 s) | `docs/evidence/alert_latency.txt` |
| Batch scoring | 100,000 vehicles in ~10 s, flat as history grows | batch logs |
| ML | ROC-AUC 0.878 vs 0.688 baseline; precision@top-2% 27.8% vs 6.6% (4.2x) | `fleetpulse/ml/metrics.json` |
| API | p95 110 ms / p99 132 ms at 50 concurrent users; p95 224 ms at 100 | `docs/evidence/api_load.txt` |
| Query tuning | 174 ms → 0.58 ms (vehicle telemetry); 27 → 0.40 ms (top risk); 2.7 → 0.15 ms (open alerts) | `docs/evidence/explain_analyze.txt` |
| Recovery | flow resumes ~26 s after a broker restart, zero loss | `docs/evidence/chaos.txt` |
| Tests | 50 unit (98% of domain modules), 8 integration, 10 contract, 6 BDD; ZAP, Trivy, Bandit, chaos; K8s on kind; all green in CI | GitHub Actions |
| Submission | Repo tag `v1.0-submission`; solution document docx + PDF in `docs/solution/` | |

**Submission (official instructions, 2026-10-01):** deadline Friday 2 Oct 2026, 11:00 AM, via a Google Form plus a
shared Google Drive folder ordered: 1 Solution Document (PDF), 2 explainer video (10 minutes max), 3 technical
artifacts (codebase, GitHub link, documentation). A ready-to-upload copy is built outside the repo at
`D:\Coding\STEP hackathon round\FleetPulse_Submission\` (rebuild it after any change).

**Explainer video:** https://drive.google.com/file/d/1R0No_tNViiExbQ-IPfvOw9y1ivHt7P9Z/view?usp=sharing (in the solution document cover and section 13, and the README).

## 7. Known gaps and planned upgrades

Gaps (also listed honestly in the README and solution document):
- 100K events/s not reached on one laptop: ~24K/s sustained with zero loss, Kafka buffers 69K/s; one Postgres primary
  is the ceiling. Next step: raw telemetry to ClickHouse or Scylla, Parquet on S3 for cold.
- Soak: after ~25 min the current hourly partition outgrows Postgres cache and 3x bursts take 30-60 s to clear.
  Quick fix: one unique (vin, ts, seq) index instead of two vin-leading indexes, larger shared_buffers.
- Device mTLS, Keycloak/OIDC and Vault are designed but the demo uses HS256 JWT with a local user table.
- ML is trained on simulated history from the same wear model as the simulator.
- Terraform (AWS) written but not applied; no long soak test beyond ~15 min; no OpenTelemetry tracing yet.

Upgrade backlog (pick from here, then log it in the changelog):
0. Merge telemetry indexes into unique (vin, ts, seq) + raise shared_buffers; re-run the 45-min soak.
1. ClickHouse for raw telemetry + Parquet cold tier with real retention/cost numbers.
2. Keycloak OIDC + mTLS for devices + secrets from Vault / K8s Secrets.
3. Helm chart and KEDA autoscaling of processors on consumer lag.
4. k6/Locust soak test at higher rates; OpenTelemetry traces across simulator → processor → API.
5. EV charging optimisation (DP over time-of-use tariffs) and nearest-depot routing (Dijkstra) in the UI.

## 8. Working agreements

- Commits are authored by the repo owner only, with plain messages and no co-author or AI attribution lines.
- Never commit secrets; config comes from the environment.
- Keep docs in sync with what actually runs: README results, ADRs, diagrams, solution document (regenerate with
  `python docs/solution/fill_template.py <template.docx> docs/solution/FleetPulse_Solution_Document.docx`, then
  export the PDF from Word).
- CI must stay green; e2e runs the integration, contract and BDD suites plus ZAP, Trivy and the chaos test.
- After a change that should be in the submission, move the tag:
  `git tag -f v1.0-submission && git push -f origin v1.0-submission`.

## 9. Changelog

Newest first. One line per change: date, what changed, why.

- 2026-10-02: Solution document cover edited by hand by the owner (title, submitted-by, date 02/10/2026); PDF exported from that docx. Do not regenerate with fill_template.py without re-applying these cover edits.
- 2026-10-02: README and solution document screenshots replaced with the owner's own captures (dashboard, vehicle drawer, Grafana).
- 2026-10-02: Explainer video recorded and linked (https://drive.google.com/file/d/1R0No_tNViiExbQ-IPfvOw9y1ivHt7P9Z/view?usp=sharing); fresh README screenshots; final PDF and submission folder.
- 2026-10-02: Explainer script shortened to ~6.5 min at the owner's request; solution document demo timeline updated.
- 2026-10-02: Honest soak results; narrated 9.5-min explainer script (docs/demo-script.md); docs and solution document refreshed.
- 2026-10-01: Fleet-wide events/s KPI (per-second buckets); soak test script.
- 2026-10-01: Pipeline/API load tooling and evidence, data freshness KPI, Grafana dashboard, K8s-on-kind CI job, coverage scope.
- 2026-10-01: Recorded the official submission format and deadline; built the Drive-ready submission folder.
- 2026-10-01: Added this PROJECT_CONTEXT.md as the living record of the project.
- 2026-10-01: Consumer session timeout 10 s; recovery test polls up to 180 s (CI chaos step was failing).
- 2026-10-01: Contract tests wait for first risk scores on a fresh stack.
- 2026-10-01: 4 processor replicas; alerts pushed before telemetry insert; copilot help reply; docs re-synced.
- 2026-10-01: BDD acceptance + contract suites; ZAP baseline; Trivy action re-pinned.
- 2026-10-01: pytest `pythonpath` so CI finds the package.
- 2026-10-01: Hourly partitions, retention and incremental rollup (bounded disk, flat batch time).
- 2026-10-01: Map tiles (Esri + OSM fallback, Referer policy), all-depot map sampling, CI lint/bandit fixes, UI polish.
- 2026-10-01: Initial FleetPulse system and solution document; tag `v1.0-submission`.
