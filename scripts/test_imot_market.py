"""Evidence and publication invariants for the asking-price comparison model."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import imot_market as market
from imot_market_format import MAX_SHARD_BYTES, json_bytes, read_state_payload, validate_public_enrichment, validate_snapshot


DATE = "2026-10-27T10:00:00Z"


def raw_offer(index, *, price=200000, **changes):
    identifier = f"1a{index:08}"
    row = {"id": identifier, "url": f"https://www.imot.bg/obiava-{identifier}-test",
           "neighborhood": "Банишора", "property_type": "2-СТАЕН", "area_m2": 80,
           "price": price, "currency": "EUR", "vat": "included", "construction_year": 2015,
           "construction_label_bg": "Тухла, 2015 г.", "floor_bg": "2 от 5", "observed_at": DATE,
           "seller_type": "agency", "seller_evidence": "agency_profile", "seller_checked_at": DATE,
           "agency": {"name": "Тест агенция", "profile_url": "https://test-agency.imot.bg/", "phone": "+359888123456", "website": "https://test-agency.example/", "checked_at": DATE, "evidence": "professional_profile"},
           "property_features": {"construction_type": "brick", "furnishing": "furnished", "building_year": 2015, "year_basis": "built", "floor_number": 2, "total_floors": 5, "elevator": "yes", "checked_at": DATE, "source": "card"},
           "analysis_method_version": 3,
           "analysis": {"completion_stage": "completed", "condition": "renovated", "area_basis": "gross", "risk_flags": [], "checked_at": DATE, "description_analyzed": True}}
    row.update(changes)
    return row


class EmptyResolver:
    reference_date = "2026-10-01"
    def resolve(self, **kwargs):
        return None


class ModelTests(unittest.TestCase):
    def build(self, rows, previous=None):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        capture = {"version": 1, "source": "imot.bg", "mode": "daily", "started_at": "2026-10-27T09:00:00Z", "completed_at": DATE, "complete": True, "offers": rows,
                   "completion": {"sources": [{"key": "test", "expected_count": len(rows), "captured_count": len(rows)}], "total_unique": len({row["id"] for row in rows})}}
        with patch.object(market, "LocationResolver", EmptyResolver):
            manifest, summary = market.build_snapshot(capture, folder.name, previous)
        root = Path(folder.name) / "market-snapshots" / manifest["snapshot_id"]
        offers = [row for shard in manifest["listing_shards"] for row in json.loads((root / shard["path"]).read_bytes())["listings"]]
        state = json.loads(read_state_payload((root / manifest["state_file"]["path"]).read_bytes(), manifest["state_file"]))
        validate_snapshot(folder.name)
        return offers, summary, state, manifest

    def test_detailed_evidence_and_range_position(self):
        offers, summary, _, _ = self.build([raw_offer(0, price=140000)] + [raw_offer(i, price=190000 + i * 3000) for i in range(1, 10)])
        candidate = offers[0]
        estimate = candidate["asking_estimate"]
        self.assertEqual(estimate["method_version"], 3)
        self.assertEqual(estimate["status"], "available")
        self.assertEqual(estimate["peer_count"], 9)
        self.assertEqual(estimate["evidence"]["quality"], "detailed")
        self.assertEqual(estimate["evidence"]["price_position"], "below_range")
        self.assertGreater(estimate["indicated_price_eur"], candidate["price_eur"])
        self.assertEqual(estimate["evidence"]["missing_fields"], ["street"])
        self.assertEqual(summary["counts"]["agency_phone_count"], 10)

    def test_structure_furnishing_elevator_and_actual_age_do_not_mix(self):
        source = raw_offer(0)
        target = market.normalize_offer(source, DATE, False)
        peers = []
        for i, (field, value) in enumerate((("construction_type", "panel"), ("furnishing", "unfurnished"), ("elevator", "no")), 1):
            changed = raw_offer(i)
            changed["property_features"][field] = value
            normalized = market.normalize_offer(changed, DATE, False)
            self.assertNotEqual(market.cohort_key(target), market.cohort_key(normalized))
        distant = raw_offer(5)
        distant["property_features"]["building_year"] = 1990
        rows, _, _ = market.peer_sample(target, [market.normalize_offer(distant, DATE, False)])
        self.assertEqual(rows, [])

    def test_planned_year_is_not_building_age(self):
        planned = raw_offer(0)
        planned["property_features"].update({"building_year": 2028, "year_basis": "planned"})
        normalized = market.normalize_offer(planned, DATE, False)
        self.assertIsNone(market.actual_building_year(normalized))
        evidence = market.estimate_evidence(normalized, "neighborhood", [2500] * 8, 0)
        self.assertIn("construction_age", evidence["missing_fields"])
        self.assertEqual(evidence["quality"], "limited")

    def test_numeric_floor_distance_and_unknown_do_not_mix(self):
        target = market.normalize_offer(raw_offer(0), DATE, False)
        distant = raw_offer(1)
        distant["property_features"].update({"floor_number": 12, "total_floors": 20})
        unknown = raw_offer(2)
        unknown["property_features"].update({"floor_number": None, "total_floors": None})
        near = raw_offer(3)
        near["property_features"]["floor_number"] = 4
        peers = [market.normalize_offer(row, DATE, False) for row in (distant, unknown, near)]
        rows, _, _ = market.peer_sample(target, peers)
        self.assertEqual([row["id"] for row in rows], [near["id"]])
        target["property_features"]["floor_number"] = 1
        rows, _, _ = market.peer_sample(target, [market.normalize_offer(near, DATE, False)])
        self.assertEqual(rows, [])

    def test_unknown_facts_are_explicit_and_separate(self):
        rows = [raw_offer(i) for i in range(10)]
        for row in rows:
            row.pop("property_features")
            row["analysis"]["condition"] = "unknown"
        offers, _, _, _ = self.build(rows)
        evidence = offers[0]["asking_estimate"]["evidence"]
        self.assertEqual(evidence["quality"], "limited")
        self.assertIn("construction_type", evidence["missing_fields"])
        self.assertIn("furnishing", evidence["missing_fields"])
        self.assertIn("elevator", evidence["missing_fields"])

    def test_self_and_duplicate_source_ids_do_not_inflate_sample(self):
        target = market.normalize_offer(raw_offer(0), DATE, False)
        peer = market.normalize_offer(raw_offer(1), DATE, False)
        rows, _, duplicates = market.peer_sample(target, [target, peer, copy.deepcopy(peer)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(duplicates, 1)

    def test_insufficient_and_risky_rows_have_no_price_position(self):
        offers, _, _, _ = self.build([raw_offer(0), raw_offer(1)])
        self.assertEqual(offers[0]["asking_estimate"]["status"], "insufficient_comparables")
        self.assertEqual(offers[0]["asking_estimate"]["evidence"]["price_position"], "unavailable")
        rows = [raw_offer(i) for i in range(10)]
        rows[0]["analysis"]["risk_flags"] = ["auction"]
        offers, _, _, _ = self.build(rows)
        self.assertEqual(offers[0]["asking_estimate"]["status"], "needs_review")
        self.assertEqual(offers[0]["asking_estimate"]["evidence"]["price_position"], "unavailable")
        self.assertFalse(offers[0]["comparison"]["alert_eligible"])

    def test_method_change_rebaselines_and_attribute_changes_suppress_alerts(self):
        rows = [raw_offer(0, price=140000)] + [raw_offer(i) for i in range(1, 10)]
        _, _, previous, _ = self.build(rows)
        previous["comparison_method_version"] = 2
        offers, summary, previous, _ = self.build(rows, previous)
        self.assertTrue(summary["history"]["methodology_changed"])
        self.assertTrue(summary["history"]["baseline"])
        self.assertEqual(summary["daily_candidates"], [])
        rows[0]["property_features"]["building_year"] = 2016
        offers, _, _, _ = self.build(rows, previous)
        self.assertTrue(offers[0]["change"]["comparison_basis_changed"])
        self.assertFalse(offers[0]["comparison"]["alert_eligible"])

    def test_professional_contacts_only_and_closed_schema(self):
        offer = market.normalize_offer(raw_offer(0), DATE, False)
        validate_public_enrichment(offer)
        private = raw_offer(0, seller_type="private", seller_evidence="explicit_private_claim")
        self.assertIsNone(market.normalize_offer(private, DATE, False)["agency"])
        for field, value in (("phone", "call +359888123456 now"), ("profile_url", "javascript:alert(1)"), ("website", "https://user:secret@example.com")):
            changed = copy.deepcopy(offer)
            changed["agency"][field] = value
            with self.assertRaises(ValueError):
                validate_public_enrichment(changed)
        changed = copy.deepcopy(offer)
        changed["agency"]["email"] = "hidden@example.com"
        with self.assertRaises(ValueError):
            validate_public_enrichment(changed)

    def test_byte_aware_shards_remain_bounded_with_enriched_rows(self):
        rows = [raw_offer(i) for i in range(260)]
        for row in rows:
            row["agency"]["name"] = "А" * 120
            row["agency"]["website"] = "https://agency.example/" + "a" * 470
        offers, _, _, manifest = self.build(rows)
        self.assertGreater(len(manifest["listing_shards"]), 1)
        self.assertTrue(all(shard["bytes"] <= MAX_SHARD_BYTES for shard in manifest["listing_shards"]))
        self.assertEqual(sum(shard["count"] for shard in manifest["listing_shards"]), len(offers))

    def test_legacy_v2_estimate_remains_readable(self):
        estimate = {"status": "available", "method_version": 2, "peer_count": 8, "location_basis": "neighborhood", "median_eur_per_sqm": 2500, "p25_eur_per_sqm": 2400, "p75_eur_per_sqm": 2600, "indicated_price_eur": 200000, "range_low_eur": 192000, "range_high_eur": 208000}
        validate_public_enrichment({"asking_estimate": estimate})


if __name__ == "__main__":
    unittest.main()
