"""OBD-II Diagnostic Trouble Code parsing. Regex is linear in payload length."""
import re
from dataclasses import dataclass

DTC_RE = re.compile(r"\b([PCBU])([0-3])([0-9A-F])([0-9A-F]{2})\b")

SYSTEMS = {"P": "Powertrain", "C": "Chassis", "B": "Body", "U": "Network"}

# Subset of SAE J2012 codes the simulator emits, with a severity (1 = info .. 5 = stop now)
KNOWN = {
    "P0301": ("Cylinder 1 misfire detected", 3),
    "P0217": ("Engine coolant over-temperature", 5),
    "P0420": ("Catalyst efficiency below threshold", 2),
    "P0171": ("System too lean (bank 1)", 2),
    "P0562": ("System voltage low", 3),
    "P0A80": ("Replace hybrid/EV battery pack", 4),
    "P0AA6": ("HV battery isolation fault", 5),
    "C0035": ("Left front wheel speed sensor", 3),
    "C1214": ("Brake control relay circuit", 4),
    "U0100": ("Lost communication with ECM", 4),
}


@dataclass(frozen=True)
class DTC:
    code: str
    system: str
    generic: bool
    description: str
    severity: int


def parse_dtcs(raw: str) -> list[DTC]:
    """Extract all DTCs from a raw OEM payload string (any delimiter, any case)."""
    out, seen = [], set()
    for m in DTC_RE.finditer(raw.upper()):
        code = "".join(m.groups())
        if code in seen:
            continue
        seen.add(code)
        desc, sev = KNOWN.get(code, ("Unknown code", 2))
        out.append(DTC(code, SYSTEMS[m.group(1)], m.group(2) in ("0", "2"), desc, sev))
    return out
