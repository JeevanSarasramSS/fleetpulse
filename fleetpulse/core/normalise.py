"""Adapter pattern: each OEM payload format maps to one canonical event."""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from .dtc import parse_dtcs


class UnknownFormat(ValueError):
    pass


@dataclass
class CanonicalEvent:
    vin: str
    ts_ms: int
    seq: int
    lat: float
    lon: float
    speed_kmh: float
    odo_km: float
    oem: str
    soc_pct: float | None = None
    fuel_pct: float | None = None
    coolant_c: float | None = None
    batt_v: float | None = None
    evt: str | None = None
    dtcs: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _iso_to_ms(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


class AuroraAdapter:
    """OEM 'Aurora': flat JSON, ISO timestamps, metric units, DTC list."""

    name = "aurora"

    @staticmethod
    def matches(p: dict) -> bool:
        return "vin" in p and "ts" in p and "speed_kmh" in p

    @staticmethod
    def to_canonical(p: dict) -> CanonicalEvent:
        return CanonicalEvent(
            vin=p["vin"].upper(), ts_ms=_iso_to_ms(p["ts"]), seq=int(p["seq"]),
            lat=float(p["lat"]), lon=float(p["lon"]), speed_kmh=float(p["speed_kmh"]),
            odo_km=float(p["odo_km"]), oem="aurora", soc_pct=p.get("soc_pct"),
            fuel_pct=p.get("fuel_pct"), coolant_c=p.get("coolant_c"), batt_v=p.get("batt_v"),
            evt=p.get("evt"), dtcs=[d.code for d in parse_dtcs(" ".join(p.get("dtc", [])))],
        )


class BorealisAdapter:
    """OEM 'Borealis': nested JSON, epoch seconds, imperial units, DTCs as a raw string."""

    name = "borealis"

    @staticmethod
    def matches(p: dict) -> bool:
        return "vehicleId" in p and "position" in p

    @staticmethod
    def to_canonical(p: dict) -> CanonicalEvent:
        pos, sig = p["position"], p.get("signals", {})
        temp_f = sig.get("coolantTempF")
        return CanonicalEvent(
            vin=p["vehicleId"].upper(), ts_ms=int(float(p["epoch"]) * 1000), seq=int(p["counter"]),
            lat=float(pos["latitude"]), lon=float(pos["longitude"]),
            speed_kmh=round(float(sig.get("speedMph", 0)) * 1.609344, 2),
            odo_km=round(float(sig.get("odometerMi", 0)) * 1.609344, 1), oem="borealis",
            soc_pct=sig.get("batteryPct"), fuel_pct=sig.get("fuelPct"),
            coolant_c=None if temp_f is None else round((temp_f - 32) * 5 / 9, 1),
            batt_v=sig.get("lvBatteryVolts"), evt=p.get("eventType"),
            dtcs=[d.code for d in parse_dtcs(p.get("faultString", ""))],
        )


ADAPTERS = [AuroraAdapter, BorealisAdapter]


def normalise(payload: dict) -> CanonicalEvent:
    for a in ADAPTERS:
        if a.matches(payload):
            return a.to_canonical(payload)
    raise UnknownFormat(f"no adapter for keys {sorted(payload)[:6]}")
