-- FleetPulse relational core (3NF) + partitioned telemetry + pgvector knowledge base.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE tenant (
  tenant_id   SMALLINT PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE subscription_plan (
  plan_code   TEXT PRIMARY KEY,
  max_vehicles INT NOT NULL,
  price_per_vehicle_usd NUMERIC(8,2) NOT NULL
);

CREATE TABLE subscription (
  subscription_id BIGSERIAL PRIMARY KEY,
  tenant_id   SMALLINT NOT NULL REFERENCES tenant,
  plan_code   TEXT NOT NULL REFERENCES subscription_plan,
  starts_on   DATE NOT NULL,
  ends_on     DATE
);

CREATE TABLE app_user (
  user_id     BIGSERIAL PRIMARY KEY,
  tenant_id   SMALLINT NOT NULL REFERENCES tenant,
  email       TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role        TEXT NOT NULL CHECK (role IN ('admin','fleet_manager','analyst'))
);

CREATE TABLE fleet (
  fleet_id    INT PRIMARY KEY,
  tenant_id   SMALLINT NOT NULL REFERENCES tenant,
  name        TEXT NOT NULL,
  home_lat    DOUBLE PRECISION NOT NULL,
  home_lon    DOUBLE PRECISION NOT NULL
);

CREATE TABLE vehicle_model (
  model_id    SMALLINT PRIMARY KEY,
  oem         TEXT NOT NULL,
  name        TEXT NOT NULL,
  powertrain  TEXT NOT NULL CHECK (powertrain IN ('ICE','HEV','EV')),
  service_interval_km INT NOT NULL
);

CREATE TABLE vehicle (
  vin         CHAR(17) PRIMARY KEY,
  fleet_id    INT NOT NULL REFERENCES fleet,
  model_id    SMALLINT NOT NULL REFERENCES vehicle_model,
  model_year  SMALLINT NOT NULL,
  last_service_odo_km REAL NOT NULL DEFAULT 0
);
CREATE INDEX vehicle_fleet_vin ON vehicle (fleet_id, vin);

CREATE TABLE driver (
  driver_id   BIGINT PRIMARY KEY,
  fleet_id    INT NOT NULL REFERENCES fleet,
  full_name   TEXT,              -- PII: nulled on erasure
  licence_no  TEXT,              -- PII: nulled on erasure
  erased_at   TIMESTAMPTZ
);

CREATE TABLE vehicle_assignment (
  vin         CHAR(17) NOT NULL REFERENCES vehicle,
  driver_id   BIGINT NOT NULL REFERENCES driver,
  assigned_from TIMESTAMPTZ NOT NULL,
  assigned_to TIMESTAMPTZ,
  PRIMARY KEY (vin, assigned_from)
);

CREATE TABLE alert (
  alert_id    BIGSERIAL PRIMARY KEY,
  tenant_id   SMALLINT NOT NULL REFERENCES tenant,   -- deliberate denormalisation: tenant filter without 3 joins
  vin         CHAR(17) NOT NULL REFERENCES vehicle,
  rule        TEXT NOT NULL,
  severity    SMALLINT NOT NULL,
  detail      JSONB NOT NULL DEFAULT '{}',
  event_ts    TIMESTAMPTZ NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  acked_by    BIGINT REFERENCES app_user,
  acked_at    TIMESTAMPTZ,
  dedup_key   TEXT NOT NULL UNIQUE                   -- idempotent alert creation
);
CREATE INDEX alert_tenant_open ON alert (tenant_id, alert_id DESC) WHERE acked_at IS NULL;
CREATE INDEX alert_tenant_id ON alert (tenant_id, alert_id DESC);

CREATE TABLE work_order (
  work_order_id BIGSERIAL PRIMARY KEY,
  tenant_id   SMALLINT NOT NULL REFERENCES tenant,
  vin         CHAR(17) NOT NULL REFERENCES vehicle,
  reason      TEXT NOT NULL,
  est_cost_usd NUMERIC(10,2),
  status      TEXT NOT NULL CHECK (status IN ('proposed','approved','rejected','done')),
  proposed_by TEXT NOT NULL,          -- 'agent' or user email
  approved_by BIGINT REFERENCES app_user,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE risk_score (
  vin         CHAR(17) PRIMARY KEY REFERENCES vehicle,
  tenant_id   SMALLINT NOT NULL,
  score       REAL NOT NULL,
  baseline_score REAL NOT NULL,
  top_factors JSONB NOT NULL,
  scored_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX risk_tenant_score ON risk_score (tenant_id, score DESC);

CREATE TABLE audit_log (
  audit_id    BIGSERIAL PRIMARY KEY,
  at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  tenant_id   SMALLINT,
  actor       TEXT NOT NULL,          -- user email or 'agent:<user>'
  action      TEXT NOT NULL,
  resource    TEXT NOT NULL,
  detail      JSONB NOT NULL DEFAULT '{}'
);
-- Append-only: no UPDATE/DELETE for the app role
CREATE OR REPLACE FUNCTION audit_immutable() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$ LANGUAGE plpgsql;
CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_immutable();

-- Telemetry (hot tier): range-partitioned by hour so retention = DROP PARTITION, index (vin, ts) inside each.
CREATE TABLE telemetry (
  vin         CHAR(17) NOT NULL,
  ts          TIMESTAMPTZ NOT NULL,
  seq         BIGINT NOT NULL,
  lat         REAL NOT NULL,
  lon         REAL NOT NULL,
  speed_kmh   REAL NOT NULL,
  odo_km      REAL NOT NULL,
  soc_pct     REAL,
  fuel_pct    REAL,
  coolant_c   REAL,
  batt_v      REAL,
  evt         TEXT,
  dtcs        TEXT[]
) PARTITION BY RANGE (ts);
CREATE UNIQUE INDEX telemetry_idem ON telemetry (vin, seq, ts);  -- idempotent sink
CREATE INDEX telemetry_vin_ts ON telemetry (vin, ts DESC);
CREATE INDEX telemetry_dtc ON telemetry (ts) WHERE dtcs IS NOT NULL;

-- Hourly partitions, the vehicle_daily rollup and retention live in 002_lifecycle.sql (also re-applied by the
-- batch job on start, so older databases are migrated in place).

-- Vector store: fault knowledge base for retrieval by the copilot.
CREATE TABLE fault_knowledge (
  kb_id       SERIAL PRIMARY KEY,
  dtc         TEXT,
  title       TEXT NOT NULL,
  body        TEXT NOT NULL,
  avg_repair_usd NUMERIC(8,2),
  embedding   vector(256) NOT NULL
);
CREATE INDEX fault_knowledge_hnsw ON fault_knowledge USING hnsw (embedding vector_cosine_ops);
