"""Real-time rule engine. Pure (no I/O) so it is unit-testable; state is per-VIN and bounded."""
from dataclasses import dataclass

from ..core.dtc import KNOWN
from ..core.normalise import CanonicalEvent
from ..core.streaming import SlidingWindow


@dataclass
class Alert:
    vin: str
    rule: str
    severity: int
    detail: dict
    event_ts_ms: int

    @property
    def dedup_key(self) -> str:
        # One alert per vehicle+rule+code per hour: replays and duplicate events are idempotent
        return f"{self.vin}:{self.rule}:{self.detail.get('code', '')}:{self.event_ts_ms // 3_600_000}"


class RuleEngine:
    OVERHEAT_C = 108.0
    LOW_12V = 11.8
    LOW_SOC = 10.0
    HARSH_BRAKES_PER_HOUR = 3

    def __init__(self, max_vehicles: int = 200_000):
        self.coolant: dict[str, SlidingWindow] = {}
        self.brakes: dict[str, SlidingWindow] = {}
        self.max_vehicles = max_vehicles

    def _win(self, store, vin, span):
        w = store.get(vin)
        if w is None:
            if len(store) >= self.max_vehicles:  # bounded memory under VIN floods
                store.pop(next(iter(store)))
            w = store[vin] = SlidingWindow(span)
        return w

    def evaluate(self, e: CanonicalEvent) -> list[Alert]:
        out, ts = [], e.ts_ms / 1000
        for code in e.dtcs:
            desc, sev = KNOWN.get(code, ("Unknown code", 2))
            rule = "CRITICAL_DTC" if sev >= 4 else "DTC"
            out.append(Alert(e.vin, rule, sev, {"code": code, "description": desc}, e.ts_ms))
        if e.coolant_c is not None:
            w = self._win(self.coolant, e.vin, 300)
            w.add(ts, e.coolant_c)
            if len(w.q) >= 2 and w.mean > self.OVERHEAT_C:
                out.append(Alert(e.vin, "OVERHEAT_TREND", 4, {"mean_c": round(w.mean, 1), "max_c": w.max}, e.ts_ms))
        if e.batt_v is not None and e.batt_v < self.LOW_12V:
            out.append(Alert(e.vin, "LOW_12V", 3, {"volts": e.batt_v}, e.ts_ms))
        if e.soc_pct is not None and e.soc_pct < self.LOW_SOC:
            out.append(Alert(e.vin, "LOW_SOC", 2, {"soc_pct": e.soc_pct}, e.ts_ms))
        if e.evt == "HARSH_BRAKE":
            w = self._win(self.brakes, e.vin, 3600)
            w.add(ts, 1.0)
            if len(w.q) >= self.HARSH_BRAKES_PER_HOUR:
                out.append(Alert(e.vin, "HARSH_BRAKE_PATTERN", 2, {"count_1h": len(w.q)}, e.ts_ms))
        return out
