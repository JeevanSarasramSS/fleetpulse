"""VIN validation (ISO 3779 / NHTSA check digit). O(17) time, O(1) space."""
import re

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # 17 chars, no I, O, Q

_TRANSLIT = {
    **{str(d): d for d in range(10)},
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def check_digit(vin17: str) -> str:
    total = sum(_TRANSLIT[c] * w for c, w in zip(vin17, _WEIGHTS))
    r = total % 11
    return "X" if r == 10 else str(r)


def is_valid_vin(vin: str) -> bool:
    if not isinstance(vin, str):
        return False
    vin = vin.upper()
    if not VIN_RE.match(vin):
        return False
    return vin[8] == check_digit(vin)


def with_check_digit(vin17: str) -> str:
    """Return the VIN with position 9 replaced by its correct check digit."""
    v = vin17.upper()
    return v[:8] + check_digit(v[:8] + "0" + v[9:]) + v[9:]
