"""Deterministic generation of the static fleet (tenants, fleets, vehicles, drivers)."""
import random
import string

from ..core.vin import with_check_digit

TENANTS = [(1, "Aurora Logistics"), (2, "Borealis Rentals"), (3, "Coastal Leasing")]
# (model_id, oem, name, powertrain, service_interval_km)
MODELS = [
    (1, "aurora", "Aurora Hauler", "ICE", 15000),
    (2, "aurora", "Aurora Volt", "EV", 30000),
    (3, "aurora", "Aurora Hybrid", "HEV", 20000),
    (4, "borealis", "Borealis Van", "ICE", 12000),
    (5, "borealis", "Borealis E-Van", "EV", 30000),
    (6, "borealis", "Borealis Cruiser", "HEV", 20000),
]
# Depot cities (lat, lon) in India; vehicles roam around their fleet's home depot
CITIES = [(13.0827, 80.2707), (12.9716, 77.5946), (19.0760, 72.8777), (28.6139, 77.2090),
          (17.3850, 78.4867), (18.5204, 73.8567), (22.5726, 88.3639), (21.1702, 72.8311)]
WMI = {"aurora": "1FP", "borealis": "2BR"}
_VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
FIRST = ["Arjun", "Priya", "Rahul", "Ananya", "Vikram", "Meera", "Karthik", "Divya", "Sanjay", "Lakshmi"]
LAST = ["Iyer", "Sharma", "Reddy", "Nair", "Gupta", "Menon", "Rao", "Patel", "Das", "Singh"]


def make_fleets(n_fleets: int = 60, seed: int = 7):
    rnd = random.Random(seed)
    out = []
    for f in range(1, n_fleets + 1):
        lat, lon = CITIES[f % len(CITIES)]
        out.append((f, TENANTS[f % len(TENANTS)][0], f"Fleet {f:03d}",
                    lat + rnd.uniform(-0.05, 0.05), lon + rnd.uniform(-0.05, 0.05)))
    return out


def make_vin(rnd: random.Random, oem: str, year: int) -> str:
    body = "".join(rnd.choice(_VIN_CHARS) for _ in range(5))
    year_code = "ABCDEFGHJKLMNPRSTVWXY123456789"[(year - 2010) % 30]
    serial = "".join(rnd.choice(string.digits) for _ in range(6))
    return with_check_digit(WMI[oem] + body + "0" + year_code + "A" + serial)


def make_vehicles(n: int, fleets, seed: int = 11):
    """Yield (vin, fleet_id, model_id, model_year, last_service_odo_km, odo_km, wear)."""
    rnd = random.Random(seed)
    seen = set()
    for _ in range(n):
        model = rnd.choice(MODELS)
        year = rnd.randint(2018, 2026)
        vin = make_vin(rnd, model[1], year)
        while vin in seen:
            vin = make_vin(rnd, model[1], year)
        seen.add(vin)
        odo = rnd.uniform(2000, 180000)
        since_service = rnd.uniform(0, model[4] * 1.4)
        # Hidden wear in [0,1]: older, high-mileage, overdue vehicles wear faster
        wear = min(1.0, rnd.betavariate(1.2, 6) + 0.25 * since_service / model[4] + 0.1 * (2026 - year) / 8)
        yield (vin, rnd.choice(fleets)[0], model[0], year, max(0.0, odo - since_service), odo, wear)


def make_drivers(n: int, fleets, seed: int = 13):
    rnd = random.Random(seed)
    for d in range(1, n + 1):
        yield (d, rnd.choice(fleets)[0], f"{rnd.choice(FIRST)} {rnd.choice(LAST)}",
               "TN" + "".join(rnd.choice(string.digits) for _ in range(11)))
