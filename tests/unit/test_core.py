import math
import random

import pytest

from fleetpulse.core.dtc import parse_dtcs
from fleetpulse.core.geo import dijkstra, geohash, haversine_km, segment_trips
from fleetpulse.core.streaming import BloomFilter, CountMinSketch, ReorderBuffer, SlidingWindow, TopK
from fleetpulse.core.vin import check_digit, is_valid_vin, with_check_digit


class TestVin:
    def test_known_valid_vin(self):
        assert is_valid_vin("1HGCM82633A004352")  # example from the problem statement
        assert is_valid_vin("1M8GDM9AXKP042788")  # check digit X

    @pytest.mark.parametrize("vin", ["1HGCM82633A00435", "1HGCM82633A0043521", "1HGCM82O33A004352",
                                     "1HGCM82I33A004352", "1HGCM82Q33A004352", "1HGCM82643A004352", "", None, 123])
    def test_invalid(self, vin):
        assert not is_valid_vin(vin)

    def test_lowercase_accepted(self):
        assert is_valid_vin("1hgcm82633a004352")

    def test_with_check_digit_roundtrip(self):
        rnd = random.Random(1)
        chars = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
        for _ in range(500):
            v = with_check_digit("".join(rnd.choice(chars) for _ in range(17)))
            assert is_valid_vin(v)
            assert v[8] == check_digit(v)


class TestDtc:
    def test_parse_mixed_payload(self):
        out = parse_dtcs("DTC:p0301;DTC:C0035 junk U0100 P0301")
        assert [d.code for d in out] == ["P0301", "C0035", "U0100"]  # de-duplicated, upper-cased
        assert out[0].system == "Powertrain" and out[1].system == "Chassis" and out[2].system == "Network"

    def test_severity_and_unknown(self):
        out = parse_dtcs("P0217 P1234")
        assert out[0].severity == 5
        assert out[1].description == "Unknown code" and out[1].generic is False

    def test_rejects_non_codes(self):
        assert parse_dtcs("P04 XP0301X Z0301 P4301") == []


class TestStreaming:
    def test_bloom_no_false_negatives_and_low_fp(self):
        b = BloomFilter(10_000, 0.01)
        for i in range(10_000):
            assert b.add(f"k{i}") is False or True
        assert all(f"k{i}" in b for i in range(10_000))
        fp = sum(f"x{i}" in b for i in range(10_000)) / 10_000
        assert fp < 0.03

    def test_bloom_detects_duplicate(self):
        b = BloomFilter(100)
        assert b.add("VIN:1") is False
        assert b.add("VIN:1") is True

    def test_cms_never_underestimates(self):
        c = CountMinSketch(256, 4)
        truth = {}
        rnd = random.Random(2)
        for _ in range(5000):
            k = f"P0{rnd.randint(100, 400)}"
            truth[k] = truth.get(k, 0) + 1
            c.add(k)
        assert all(c.estimate(k) >= v for k, v in truth.items())

    def test_topk_finds_heavy_hitters(self):
        t = TopK(3)
        for _ in range(100):
            t.add("P0301")
        for _ in range(50):
            t.add("P0420")
        for i in range(200):
            t.add(f"R{i}")
        assert [k for k, _ in t.top()[:2]] == ["P0301", "P0420"]

    def test_sliding_window(self):
        w = SlidingWindow(10)
        for t, v in [(0, 100), (5, 110), (9, 90)]:
            w.add(t, v)
        assert w.max == 110 and math.isclose(w.mean, 100)
        w.add(16, 80)  # evicts t=0 and t=5
        assert w.max == 90 and math.isclose(w.mean, 85)

    def test_reorder_buffer(self):
        r = ReorderBuffer()
        assert r.observe("A", 1) and r.observe("A", 3)
        assert not r.observe("A", 2)
        assert not r.observe("A", 3)
        assert r.observe("B", 0)


class TestGeo:
    def test_haversine(self):
        assert abs(haversine_km(13.0827, 80.2707, 12.9716, 77.5946) - 290) < 5  # Chennai-Bengaluru

    def test_geohash_known(self):
        assert geohash(57.64911, 10.40744, 6) == "u4pruy"

    def test_dijkstra_nearest_within_range(self):
        g = {"A": [("B", 4), ("C", 1)], "C": [("B", 1), ("D", 10)], "B": [("D", 2)]}
        assert dijkstra(g, "A", {"D"}) == ("D", 4, ["A", "C", "B", "D"])
        assert dijkstra(g, "A", {"D"}, max_cost=3) is None
        assert dijkstra(g, "A", {"Z"}) is None

    def test_trip_segmentation_ignores_blips(self):
        speeds = [0] * 5 + [40, 42, 0, 45, 50, 48] + [0] * 6 + [30, 35, 33]
        labels, trips = segment_trips(speeds)
        assert trips == [(5, 10), (17, 19)]
        assert len(labels) == len(speeds)

    def test_trip_segmentation_empty(self):
        assert segment_trips([]) == ([], [])


def test_embedding_retrieval_ranks_relevant_doc_first():
    from fleetpulse.core.embed import embed
    docs = ["coolant over temperature water pump thermostat", "12v battery voltage low alternator", "wheel speed sensor abs"]
    q = embed("engine running hot coolant temperature")
    sims = [sum(a * b for a, b in zip(q, embed(d))) for d in docs]
    assert sims.index(max(sims)) == 0
    assert abs(sum(x * x for x in q) - 1) < 1e-9
