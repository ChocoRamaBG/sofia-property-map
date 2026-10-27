"""Meaningful offline v2 evidence-level and integrity regressions."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import business_snapshot_v2 as v2
import municipal_business_addresses as municipal
import refresh_business_addresses as base

STAMP = "2026-10-27T10:00:00+00:00"
CID1, CID2 = "68134.100.1", "68134.100.2"
AID = "address-" + "a" * 24


def uic(number):
    prefix = str(90_000_000 + number)
    check = sum((i + 1) * int(x) for i, x in enumerate(prefix)) % 11
    if check == 10:
        check = sum((i + 3) * int(x) for i, x in enumerate(prefix)) % 11
        if check == 10:
            check = 0
    return prefix + str(check)


def company(number=0, method="cadastre_address", label="гр. София, ул. тестова № 1"):
    return {"uic": uic(number), "name": "Фиктивно дружество", "legal_form": "Дружество с ограничена отговорност", "activity": "",
            "registered_address": label, "status": "not_verified", "as_of": "2026-10-25", "source_url": base.source_url(uic(number)),
            "match_method": method, "reference_ids": [] if method == "cadastre_address" else ["rn-" + str(number)]}


def provenance():
    sources = []
    for index, spec in enumerate(municipal.SOURCES.values()):
        filename = "address_sofia.zip" if index == 0 else "streets_names_new_old.zip"
        sources.append({"dataset": spec["dataset"], "resource_id": spec["resource_id"], "format": spec["format"],
                        "url": "https://urbandata.sofia.bg/dataset/" + "a" * 36 + "/resource/" + spec["resource_id"] + "/download/" + filename,
                        "data_as_of": "2026-08-28", "retrieved_at": STAMP, "bytes": 100, "sha256": str(index + 1) * 64,
                        "metadata_sha256": str(index + 3) * 64, "license_id": "CC-BY-4.0", "license_url": municipal.LICENSE_URL, "policy_url": municipal.POLICY_URL})
    revision = hashlib.sha256(municipal.json_bytes([{k: s[k] for k in ("resource_id", "sha256", "metadata_sha256")} for s in sources])).hexdigest()
    return {"version": 1, "sources": sources, "coordinate_crs": "OGC:CRS84", "crs_basis": "GeoJSON_default_CRS84", "publisher_crs_explicit": False, "source_revision": revision}


class BusinessSnapshotV2Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="business-v2-fixture-")
        self.root = Path(self.temporary.name)
        self.source = {"repo": base.REPO, "commit": "a" * 40, "path": base.SOURCE_PATH,
                       "files": [{"name": "registry_agency_data_mega.csv", "bytes": 100, "git_blob_sha1": "b" * 40, "sha256": "c" * 64}]}
        self.cadastre = {"manifest_sha256": "d" * 64, "snapshot_id": "d" * 32, "captured_from": STAMP, "captured_to": STAMP,
                         "sources": [{"code": f"sofia-district-{i:02d}", "source_url": f"https://kais.cadastre.bg/bg/OpenData/Download?path=fixture-{i}", "zip_sha256": "e" * 64, "captured_at": STAMP} for i in range(24)]}
        self.parcels = {CID1: [company()], CID2: [company(1, "municipal_parcel", "гр. София, ул. тестова № 2")]}
        self.addresses = {AID: {"address_label": "гр. София, ж.к. пример, бл. 3", "lat": 42.71, "lng": 23.31,
                                "companies": [company(2, "municipal_address", "гр. София, ж.к. пример, бл. 3")]}}
        self.points = {CID1: {"lat": 42.7, "lng": 23.3}, CID2: {"lat": 42.72, "lng": 23.32}}
        self.counts = Counter({"sofia_candidates": 3, "matched_companies": 2, "matched_parcels": 2, "address_only_companies": 1,
                               "address_only_locations": 1, "exact_cadastral_address_companies": 1, "municipal_parcel_companies": 1})
        self.manifest = v2.write_snapshot(self.root, self.parcels, self.addresses, self.source, self.cadastre, self.counts, self.points, provenance())
        self.directory = self.root / "business-snapshots" / self.manifest["snapshot_id"]

    def tearDown(self):
        self.temporary.cleanup()

    def commit_manifest(self):
        raw = base.json_bytes(self.manifest)
        (self.directory / "manifest.json").write_bytes(raw)
        pointer = {"version": 1, "snapshot_id": self.manifest["snapshot_id"], "manifest_sha256": hashlib.sha256(raw).hexdigest()}
        (self.root / "business-active.json").write_bytes(base.json_bytes(pointer))

    def change_file(self, filename, change):
        path = self.directory / filename
        value = json.loads(path.read_bytes())
        change(value)
        raw = base.json_bytes(value)
        path.write_bytes(raw)
        for group in ("shards", "address_shards"):
            if filename in self.manifest[group]:
                self.manifest[group][filename] = base.descriptor(raw)
                break
        else:
            for key in ("parcel_index", "search_index", "points_index", "address_index"):
                if self.manifest[key]["file"] == filename:
                    self.manifest[key] = base.descriptor(raw, filename)
                    break
        self.commit_manifest()

    def test_valid_snapshot_reconciles_three_evidence_levels(self):
        result = v2.validate_snapshot(self.root)
        self.assertEqual(result["version"], 2)
        self.assertEqual(result["counts"]["located_companies"], 3)
        self.assertEqual(result["counts"]["located_locations"], 3)
        self.assertEqual(result["counts"]["exact_cadastral_address_companies"], 1)
        self.assertEqual(result["counts"]["municipal_parcel_companies"], 1)
        self.assertEqual(result["counts"]["address_only_companies"], 1)
        self.assertEqual(base.validate_snapshot(self.root), result)

    def test_address_only_evidence_never_contains_a_cadastral_identifier(self):
        search = json.loads((self.directory / "search-index.json").read_bytes())
        address_row = next(row for row in search if "address_id" in row)
        self.assertNotIn("cadastral_id", address_row)
        self.change_file("search-index.json", lambda rows: next(row for row in rows if "address_id" in row).update({"cadastral_id": CID1}))
        with self.assertRaises(ValueError):
            v2.validate_snapshot(self.root)

    def test_one_company_cannot_exist_at_both_match_levels(self):
        def duplicate(groups):
            record = groups[AID]["companies"][0]
            record["uic"] = uic(0)
            record["source_url"] = base.source_url(uic(0))
        self.change_file("addresses-000.json", duplicate)
        with self.assertRaises(ValueError):
            v2.validate_snapshot(self.root)

    def test_each_coverage_level_is_reconciled(self):
        original = deepcopy(self.manifest)
        for key in ["matched_companies", "matched_parcels", "address_only_companies", "address_only_locations", "exact_cadastral_address_companies",
                    "municipal_parcel_companies", "mapped_companies", "unmapped_companies", "located_companies", "located_locations"]:
            with self.subTest(key=key):
                self.manifest = deepcopy(original)
                self.manifest["counts"][key] += 1
                self.commit_manifest()
                with self.assertRaises(ValueError):
                    v2.validate_snapshot(self.root)

    def test_reference_ids_are_bounded_unique_and_required_for_municipal_matches(self):
        for refs in [[], ["r"] * 2, ["r" + str(i) for i in range(33)], ["../../outside"], ["r" * 81]]:
            with self.subTest(refs=refs):
                record = company(1, "municipal_parcel")
                record["reference_ids"] = refs
                with self.assertRaises(ValueError):
                    v2.validate_company(record)
        record = company()
        record["reference_ids"] = ["not-allowed-for-exact"]
        with self.assertRaises(ValueError):
            v2.validate_company(record)

    def test_unknown_fields_contacts_and_personal_identifiers_are_rejected(self):
        for update in [{"owners": "prohibited"}, {"activity": "email: fixture@example.invalid"}, {"name": "Личен номер 1234567890"}, {"registered_address": "телефон: 0888888888"}]:
            with self.subTest(update=update):
                record = company()
                record.update(update)
                with self.assertRaises(ValueError):
                    v2.validate_company(record)

    def test_all_allowlisted_company_fields_keep_their_string_types(self):
        for field in ["activity", "as_of"]:
            for value in [None, False, 0, []]:
                with self.subTest(field=field, value=value):
                    record = company()
                    record[field] = value
                    with self.assertRaises(ValueError):
                        v2.validate_company(record)

    def test_company_match_method_must_agree_with_address_or_parcel_level(self):
        with self.assertRaises(ValueError):
            v2.validate_company(company(1, "municipal_address"), address_only=False)
        with self.assertRaises(ValueError):
            v2.validate_company(company(1, "municipal_parcel"), address_only=True)

    def test_municipal_source_hash_identity_and_license_tampering_are_rejected(self):
        for mutate in [lambda p: p["sources"][0].update({"sha256": "f" * 64}),
                       lambda p: p["sources"][0].update({"metadata_sha256": "f" * 64}),
                       lambda p: p["sources"][0].update({"url": "https://example.invalid/source.zip"}),
                       lambda p: p["sources"][0].update({"license_url": "https://example.invalid/license"}),
                       lambda p: p.update({"source_revision": "0" * 64})]:
            bad = provenance()
            mutate(bad)
            with self.assertRaises(ValueError):
                v2.validate_municipal_source(bad)

    def test_municipal_data_dates_are_calendar_dates(self):
        for value in ["2026-99-99", "2026-02-30", [], False, 0]:
            with self.subTest(value=value):
                bad = provenance()
                bad["sources"][0]["data_as_of"] = value
                with self.assertRaises(ValueError):
                    v2.validate_municipal_source(bad)

    def test_points_are_bounded_and_must_belong_to_an_indexed_parcel(self):
        original = (self.directory / "points-index.json").read_bytes()
        for change in [lambda points: points[CID1].update({"lat": 0}), lambda points: points.update({"68134.999.999": {"lat": 42.7, "lng": 23.3}}),
                       lambda points: points[CID1].update({"lng": "23.3"})]:
            with self.subTest(change=change):
                (self.directory / "points-index.json").write_bytes(original)
                self.change_file("points-index.json", change)
                with self.assertRaises(ValueError):
                    v2.validate_snapshot(self.root)

    def test_address_index_cannot_lie_about_count_or_coordinates(self):
        self.change_file("address-index.json", lambda index: index[AID].update({"company_count": 2}))
        with self.assertRaises(ValueError):
            v2.validate_snapshot(self.root)

    def test_shard_byte_tampering_and_pointer_tampering_fail_closed(self):
        path = self.directory / "companies-000.json"
        raw = path.read_bytes()
        path.write_bytes(b" " + raw[1:])
        with self.assertRaises(ValueError):
            v2.validate_snapshot(self.root)
        path.write_bytes(raw)
        pointer = json.loads((self.root / "business-active.json").read_bytes())
        pointer["manifest_sha256"] = "0" * 64
        (self.root / "business-active.json").write_bytes(base.json_bytes(pointer))
        with self.assertRaises(ValueError):
            v2.validate_snapshot(self.root)

    def test_unlisted_snapshot_files_are_rejected(self):
        (self.directory / "raw-company-data.csv").write_text("prohibited transient input", encoding="utf-8")
        with self.assertRaises(ValueError):
            v2.validate_snapshot(self.root)

    def test_enrichment_keeps_road_point_address_only_and_quarantines_multilocation(self):
        # Real enrichment orchestration, synthetic municipal and cadastral
        # evidence. A road/boundary result must never gain a cadastral ID.
        base_record = company(10)
        for key in ["match_method", "reference_ids"]:
            base_record.pop(key)
        selected = {uic(i): ("date", "hash", dict(base_record, uic=uic(i), source_url=base.source_url(uic(i))), None, "") for i in range(10, 14)}
        raw = {uic(10): {"unique"}, uic(11): {"road"}, uic(12): {"multiple"}, uic(13): {"different-labels"}}
        def candidate(label, points):
            return {"address_label": label, "points": [{"lat": lat, "lng": lng, "reference_id": "r" + str(i)} for i, (lat, lng) in enumerate(points)],
                    "reference_ids": ["r" + str(i) for i in range(len(points))], "method": "municipal_street_number"}
        def resolve(value, _):
            if value == "different-labels":
                return [candidate("гр. София, ул. тестова № 1", [(42.7, 23.3)]), candidate("гр. София, ул. друга № 1", [(42.7, 23.3)])]
            coordinates = [(42.7, 23.3)] if value == "unique" else [(42.71, 23.31)] if value == "road" else [(42.72, 23.32), (42.73, 23.33)]
            return [candidate("гр. София, ул. тестова № 1", coordinates)]
        class Linker:
            def resolve(self, points):
                return {"status": "unique", "cadastral_id": CID1} if points[0]["lat"] == 42.7 else {"status": "road"} if len(points) == 1 else {"status": "multiple"}
        args = SimpleNamespace(municipal_cache=Path("unused"), municipal_offline=True, cadastre_manifest=Path("unused"), cadastre_archives=Path("unused"))
        counts = Counter()
        with patch("municipal_business_addresses.capture_reference", return_value=(object(), provenance())), patch("municipal_business_addresses.resolve_company_address", side_effect=resolve), \
             patch("business_parcel_linker.build_index", return_value=Linker()), patch.object(v2, "selected_raw_addresses", return_value=raw):
            parcels, addresses, _ = v2.enrich(Path("unused"), self.source, selected, {}, args, counts)
        self.assertEqual([c["uic"] for c in parcels[CID1]], [uic(10)])
        self.assertEqual(parcels[CID1][0]["match_method"], "municipal_parcel")
        self.assertEqual(len(addresses), 1)
        address_company = next(iter(addresses.values()))["companies"][0]
        self.assertEqual(address_company["uic"], uic(11))
        self.assertEqual(address_company["match_method"], "municipal_address")
        self.assertNotIn("cadastral_id", address_company)
        self.assertEqual(counts["municipal_multilocation_unresolved"], 1)
        self.assertEqual(counts["municipal_ambiguous_address"], 1)


if __name__ == "__main__":
    unittest.main()
