-- Data lifecycle: hot raw telemetry (hourly partitions, short retention) -> warm vehicle_daily rollup (kept)
-- -> cold archive (out of scope locally; see ADR-0002). Idempotent: run by initdb and by the batch job on start.

-- Catches events whose hour has no partition (e.g. a Kafka replay older than retention) so one stray event
-- can never wedge the processor; cleared by drop_old_telemetry().
CREATE TABLE IF NOT EXISTS telemetry_default PARTITION OF telemetry DEFAULT;

DROP FUNCTION IF EXISTS ensure_telemetry_partitions(INT, INT);  -- older version took days, not hours
CREATE FUNCTION ensure_telemetry_partitions(hours_back INT, hours_ahead INT) RETURNS void AS $$
DECLARE h TIMESTAMPTZ;
BEGIN
  FOR h IN SELECT generate_series(date_trunc('hour', now()) - make_interval(hours => hours_back),
                                  date_trunc('hour', now()) + make_interval(hours => hours_ahead), interval '1 hour') LOOP
    BEGIN
      EXECUTE format('CREATE TABLE IF NOT EXISTS %I PARTITION OF telemetry FOR VALUES FROM (%L) TO (%L)',
                     'telemetry_' || to_char(h AT TIME ZONE 'UTC', 'YYYYMMDDHH24'), h, h + interval '1 hour');
    EXCEPTION WHEN invalid_object_definition OR check_violation THEN
      NULL;  -- range already covered (e.g. a daily partition from an older schema version)
    END;
  END LOOP;
END $$ LANGUAGE plpgsql;

-- Drops every partition whose upper bound is older than keep_hours; returns how many were dropped.
CREATE OR REPLACE FUNCTION drop_old_telemetry(keep_hours INT) RETURNS INT AS $$
DECLARE r RECORD; n INT := 0; cutoff TIMESTAMPTZ := now() - make_interval(hours => keep_hours);
BEGIN
  FOR r IN SELECT c.relname, substring(pg_get_expr(c.relpartbound, c.oid) FROM 'TO \(''([^'']+)''\)')::timestamptz AS upper
           FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
           WHERE i.inhparent = 'telemetry'::regclass AND c.relname <> 'telemetry_default' LOOP
    IF r.upper <= cutoff THEN
      EXECUTE format('DROP TABLE %I', r.relname);
      n := n + 1;
    END IF;
  END LOOP;
  DELETE FROM telemetry_default WHERE ts < cutoff;
  RETURN n;
END $$ LANGUAGE plpgsql;

-- Warm tier: per-vehicle daily rollup, maintained incrementally (only rows since the last watermark are read),
-- so the batch cost stays flat as history grows and survives raw-partition drops. Older versions used a
-- materialised view that re-scanned all telemetry every run.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_matviews WHERE matviewname = 'vehicle_daily') THEN
    DROP MATERIALIZED VIEW vehicle_daily;
  END IF;
END $$;
CREATE TABLE IF NOT EXISTS vehicle_daily (
  vin          CHAR(17) NOT NULL,
  day          DATE NOT NULL,
  events       BIGINT NOT NULL,
  min_odo      REAL,
  max_odo      REAL,
  sum_speed    DOUBLE PRECISION NOT NULL,
  max_coolant  REAL,
  min_batt_v   REAL,
  harsh_brakes INT NOT NULL,
  idle_samples INT NOT NULL,
  dtc_events   INT NOT NULL,
  PRIMARY KEY (vin, day)
);
CREATE TABLE IF NOT EXISTS rollup_watermark (
  name  TEXT PRIMARY KEY,
  upto  TIMESTAMPTZ NOT NULL
);

SELECT ensure_telemetry_partitions(2, 24);
