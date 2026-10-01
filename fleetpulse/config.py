"""12-factor config: everything comes from the environment."""
import os


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


KAFKA_BOOTSTRAP = env("KAFKA_BOOTSTRAP", "localhost:9092")
PG_DSN = env("PG_DSN", "postgresql://fleet:fleet@localhost:5432/fleet")
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
JWT_SECRET = env("JWT_SECRET", "dev-only-change-me")
JWT_TTL_MIN = int(env("JWT_TTL_MIN", "120"))
RATE_LIMIT_PER_MIN = int(env("RATE_LIMIT_PER_MIN", "600"))
TOPIC_RAW = env("TOPIC_RAW", "telemetry.raw")
TOPIC_DLQ = env("TOPIC_DLQ", "telemetry.dlq")
TOPIC_ALERTS = env("TOPIC_ALERTS", "alerts")
NUM_VEHICLES = int(env("NUM_VEHICLES", "100000"))
EVENTS_PER_SEC = int(env("EVENTS_PER_SEC", "5000"))
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-sonnet-5-5")
