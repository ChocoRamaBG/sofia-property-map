"""Tests for evidence selection and conservative business-address association."""
import csv
import importlib.util
from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import refresh_business_addresses as business


def test_uic(first="12345678"):
    for check in "0123456789":
        if business.valid_uic(first + check):
            return first + check
    raise AssertionError("Cannot construct fixture UIC")


def row(**changes):
    values = {"uic": test_uic(), "query": test_uic(), "name": "ПРИМЕР ЕООД",
              "legal_form": "Еднолично дружество с ограничена отговорност", "country": "БЪЛГАРИЯ",
              "settlement": "гр. София, п.к. 1000", "address": "ул. Пример № 12, ет. 4, ап. 5",
              "activity": "Търговия със стоки.", "natural_person": "", "as_of": "Състояние към дата 01.10.2026 г."}
    values.update(changes)
    return {business.FIELD_MAP[k]: v for k, v in values.items()}


class AddressEvidenceTests(unittest.TestCase):
    def test_uic_checksum_and_query_must_both_confirm_identity(self):
        self.assertTrue(business.valid_uic(test_uic()))
        self.assertFalse(business.valid_uic("123456780"))
        self.assertFalse(business.valid_uic(test_uic() + "0000"))
        self.assertIsNone(business.candidate(row(query="000000000"), Counter()))

    def test_street_number_suffix_and_kind_are_not_guessed(self):
        base = business.address_key('бул. "Пример" № 12А, вх. Б')
        self.assertEqual(base, ("68134", "boulevard", "пример", "12а"))
        self.assertNotEqual(base, business.address_key("бул. Пример № 12, ет. 1"))
        self.assertNotEqual(base, business.address_key("бул. Пример № 12A, ет. 1"))
        self.assertNotEqual(base, business.address_key("ул. Пример № 12А, ет. 1"))
        for address in ("ул. Пример № 12-14", "ул. Пример № 12/14", "ул. Пример № 12 и 14", "кв. Пример, бл. 12", "ул. Пример № 12, ул. Друг № 14", "ул. Пример без номер"):
            self.assertIsNone(business.address_key(address), address)

    def test_source_generic_field_label_is_removed_only_before_explicit_kind(self):
        self.assertEqual(business.address_key("р-н Пример, бул./ул. ул. Пример № 12"), business.address_key("ул. Пример № 12"))
        self.assertEqual(business.address_key("р-н Пример, бул./ул. бул. Пример № 12"), business.address_key("бул. Пример № 12"))
        self.assertEqual(business.address_key("р-н Пример, бул./ул. Пример № 12"), ("68134", "unknown", "пример", "12"))
        self.assertIsNone(business.address_key("ул. Пример № 12, бул./ул. ул. Друг № 12"))

    def test_unknown_kind_resolves_only_after_union_of_all_official_kinds(self):
        selected, counts = self.select([row(address="бул./ул. Пример № 12")])
        self.assertEqual(selected[test_uic()][2]["registered_address"], "")
        street = ("68134", "street", "пример", "12")
        boulevard = ("68134", "boulevard", "пример", "12")
        matched = business.match_companies(selected, {boulevard: {"68134.1.2"}}, counts)
        self.assertEqual(matched["68134.1.2"][0]["registered_address"], "гр. София, бул. пример № 12")
        business.validate_company(matched["68134.1.2"][0])
        selected, counts = self.select([row(address="бул./ул. Пример № 12")])
        self.assertFalse(business.match_companies(selected, {street: {"68134.1.1"}, boulevard: {"68134.1.2"}}, counts))
        self.assertEqual(counts["ambiguous_cadastral_address"], 1)

    def test_known_unit_and_contact_tails_never_supply_the_house_number(self):
        expected = ("68134", "street", "пример", "12а")
        for address in ("ул. Пример №: 12А, ап. № 7", "ул. Пример № 12А телефон: 0888123456", "ул. Пример № 12А ет. 2", "ул. Пример 12А, вх. Б, ап. 7"):
            self.assertEqual(business.address_key(address), expected, address)
        self.assertEqual(business.address_key("ул. Пример № 12 телефон: 0888123456"), ("68134", "street", "пример", "12"))
        for address in ("ул. Пример ап. № 12", "ул. Пример, ап. № 12", "ул. Пример телефон № 12", "ул. Пример ап. 12", "ул. Пример № 12, № 14", "ул. Пример № 12, телефон: № 14", "ул. Пример № 12, snap. №14", "ул. Пример № 12, снап. №14"):
            self.assertIsNone(business.address_key(address), address)

    def test_new_formats_preserve_suffix_and_reject_ranges_and_partial_names(self):
        for address in ("бул./ул. Пример №12-14", "бул./ул. Пример №12/14", "ул. Пример №12,14", "ул. Пример 12-14", "ул. Пример №12 и 14", "бул./ул. Пример №12, бул. Друг №14"):
            self.assertIsNone(business.address_key(address), address)
        key = business.address_key("бул./ул. Пример №12А")
        self.assertFalse(business.address_matches(key, {("68134", "street", "примерна", "12а"): {"68134.1.1"}}))
        self.assertFalse(business.address_matches(key, {("68134", "street", "пример", "12a"): {"68134.1.1"}}))
        with self.assertRaises(ValueError):
            business.canonical_address(key)

    def test_contacts_units_and_other_data_are_never_copied(self):
        data = row(address="ул. Пример № 12, ет. 4, ап. 5, тел: 0888123456, owner@example.com", activity="Търговия. Тел: 0888123456")
        data["Other_Data"] = '{"owners":"PRIVATE PERSON 1234567890"}'
        company = business.candidate(data, Counter())[3]
        encoded = json.dumps(company, ensure_ascii=False)
        self.assertEqual(company["registered_address"], "гр. София, ул. пример № 12")
        for secret in ("0888123456", "owner@example.com", "ап. 5", "PRIVATE PERSON", "1234567890", "Other_Data"):
            self.assertNotIn(secret, encoded)
        self.assertEqual(company["activity"], "")
        self.assertEqual(set(company), business.COMPANY_FIELDS)

    def test_city_country_and_corporate_scope_are_explicit(self):
        for changed in ({"country": ""}, {"country": "СЪРБИЯ"}, {"settlement": "София област"}, {"settlement": "с. София"}, {"natural_person": "Да"}, {"legal_form": "Едноличен търговец"}):
            self.assertTrue(business.candidate(row(**changed), Counter())[5])
        self.assertFalse(business.candidate(row(), Counter())[5])

    def test_missing_invalid_and_ambiguous_as_of_remain_explicitly_unknown(self):
        for value in ("", "без дата", "31.02.2026", "01.10.2026 и 02.10.2026", "01.01.2999"):
            self.assertEqual(business.candidate(row(as_of=value), Counter())[3]["as_of"], "")
        self.assertEqual(business.as_of_date("Състояние към дата: 01.10.2026 г."), "2026-10-01")

    def test_undated_company_is_retained_but_conflicting_undated_is_quarantined(self):
        selected, counts = self.select([row(as_of="")])
        self.assertEqual(selected[test_uic()][2]["as_of"], "")
        self.assertEqual(counts["undated_confirmed_companies"], 1)
        selected, _ = self.select([row(as_of=""), row(as_of="", address="ул. Пример № 99")])
        self.assertFalse(selected)

    def select(self, rows):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            name = "registry_agency_data_mega.csv"
            fields = list(business.FIELD_MAP.values())
            with (root / name).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            return business.select_companies(root, {"files": [{"name": name}]})

    def test_newest_valid_observation_wins_not_last_file_order(self):
        selected, counts = self.select([row(address="ул. Пример № 99", as_of="02.10.2026"), row(as_of="01.10.2026"), row(as_of="")])
        self.assertEqual(selected[test_uic()][3][-1], "99")
        self.assertEqual(counts["missing_or_invalid_as_of"], 1)

    def test_equal_latest_date_conflict_is_quarantined(self):
        selected, counts = self.select([row(), row(address="ул. Пример № 99")])
        self.assertFalse(selected)
        self.assertEqual(counts["latest_date_conflicting_companies"], 1)
        selected, _ = self.select([row(), row(address="ул. Пример № 99"), row(address="ул. Пример № 70", as_of="02.10.2026")])
        self.assertEqual(selected[test_uic()][3][-1], "70")

    def test_newer_non_sofia_record_prevents_older_sofia_assignment(self):
        selected, counts = self.select([row(), row(settlement="гр. Пловдив", as_of="02.10.2026")])
        key = business.address_key("ул. Пример № 12")
        self.assertFalse(business.match_companies(selected, {key: {"68134.1.1"}}, counts))

    def test_multi_parcel_address_never_selects_first(self):
        selected, counts = self.select([row()])
        key = business.address_key("ул. Пример № 12")
        self.assertFalse(business.match_companies(selected, {key: {"68134.1.1", "68134.1.2"}}, counts))
        self.assertEqual(counts["ambiguous_cadastral_address"], 1)
        self.assertEqual(counts["matched_companies"], 0)

    def test_discovery_accepts_all_later_parts_but_requires_complete_set(self):
        files = [{"name": "registry_agency_data_mega" + (f"_part{i}" if i > 1 else "") + ".csv", "bytes": 10, "git_blob_sha1": "a" * 40, "sha256": "b" * 64} for i in range(1, 13)]
        source = {"repo": business.REPO, "path": business.SOURCE_PATH, "commit": "a" * 40, "files": files}
        business.validate_source(source)
        self.assertEqual(business.part_number("registry_agency_data_mega_part10.csv"), 10)
        with self.assertRaises(ValueError):
            business.validate_source(source | {"files": files[:-2] + files[-1:]})

    def test_growing_export_above_one_gib_is_accepted_with_individual_bounds(self):
        files = [{"name": "registry_agency_data_mega" + (f"_part{i}" if i > 1 else "") + ".csv", "bytes": 128 * 1024 * 1024, "git_blob_sha1": "a" * 40, "sha256": "b" * 64} for i in range(1, 17)]
        source = {"repo": business.REPO, "path": business.SOURCE_PATH, "commit": "a" * 40, "files": files}
        business.validate_source(source)
        with self.assertRaises(ValueError):
            business.validate_source(source | {"files": [files[0] | {"bytes": 128 * 1024 * 1024 + 1}, *files[1:]]})

    def test_blob_git_hash_and_local_sha_are_both_checked(self):
        import hashlib
        payload = b"test,csv\n"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.csv"
            path.write_bytes(payload)
            item = {"bytes": len(payload), "git_blob_sha1": hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest(), "sha256": hashlib.sha256(payload).hexdigest()}
            business.verify_blob(path, item)
            with self.assertRaises(ValueError):
                business.verify_blob(path, item | {"git_blob_sha1": "a" * 40})

    def snapshot(self, root, points=None):
        company = business.candidate(row(), Counter())[3]
        source = {"repo": business.REPO, "path": business.SOURCE_PATH, "commit": "a" * 40,
                  "files": [{"name": "registry_agency_data_mega.csv", "bytes": 10, "git_blob_sha1": "b" * 40, "sha256": "c" * 64}]}
        cadastre = {"manifest_sha256": "d" * 64, "snapshot_id": "e" * 32, "captured_from": "2026-10-01T00:00:00Z", "captured_to": "2026-10-01T00:00:00Z",
                    "sources": [{"code": f"sofia-district-{i:02d}", "source_url": f"https://kais.cadastre.bg/bg/OpenData/Download?path=district-{i}", "zip_sha256": "f" * 64, "captured_at": "2026-10-01T00:00:00Z"} for i in range(24)]}
        return business.write_snapshot(root, {"68134.1.1": [company]}, source, cadastre, {"matched_companies": 1, "matched_parcels": 1, "sofia_candidates": 1}, points)

    def test_legacy_snapshot_remains_valid_without_points(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.snapshot(Path(temporary))
            self.assertNotIn("points_index", manifest)

    def test_points_index_membership_and_map_coverage_reconcile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.snapshot(root, {"68134.1.1": {"lat": 42.7, "lng": 23.3}})
            self.assertEqual(manifest["counts"]["mapped_business_parcels"], 1)
            self.assertEqual(manifest["counts"]["mapped_companies"], 1)
            self.assertEqual(manifest["counts"]["unmapped_business_parcels"], 0)
            self.assertEqual(business.validate_snapshot(root)["points_index"]["file"], "points-index.json")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.snapshot(root, {})
            self.assertEqual(manifest["counts"]["mapped_companies"], 0)
            self.assertEqual(manifest["counts"]["unmapped_companies"], 1)
            self.assertEqual(manifest["counts"]["unmapped_business_parcels"], 1)
            self.assertEqual(manifest["counts"]["matched_companies"], 1)

    def test_points_reject_unknown_parcels_nonfinite_and_outside_sofia(self):
        for points in ({"68134.9.9": {"lat": 42.7, "lng": 23.3}}, {"68134.1.1": {"lat": 44., "lng": 23.3}}, {"68134.1.1": {"lat": True, "lng": 23.3}}, {"68134.1.1": {"lat": float("nan"), "lng": 23.3}}):
            with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
                self.snapshot(Path(temporary), points)

    def test_points_hash_and_coverage_count_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.snapshot(root, {"68134.1.1": {"lat": 42.7, "lng": 23.3}})
            directory = root / "business-snapshots" / manifest["snapshot_id"]
            manifest["counts"]["mapped_companies"] = 0
            (directory / "manifest.json").write_bytes(business.json_bytes(manifest))
            with self.assertRaisesRegex(ValueError, "coverage counts"):
                business.validate_snapshot(root, manifest["snapshot_id"])
            (directory / "points-index.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash or length"):
                business.validate_snapshot(root, manifest["snapshot_id"])

    def test_snapshot_validator_reconciles_hashes_indexes_and_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.snapshot(root)
            self.assertEqual(business.validate_snapshot(root)["counts"]["matched_companies"], 1)
            search = root / "business-snapshots" / manifest["snapshot_id"] / "search-index.json"
            search.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash or length"):
                business.validate_snapshot(root)

    def test_publisher_validation_rejects_unexpected_private_fields(self):
        company = business.candidate(row(), Counter())[3]
        with self.assertRaises(ValueError):
            business.validate_company(company | {"owners": "PRIVATE PERSON"})
        with self.assertRaises(ValueError):
            business.validate_company(company | {"activity": "ЕГН: 1234567890"})

    def test_snapshot_pointer_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.snapshot(root)
            pointer_path = root / "business-active.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["manifest_sha256"] = "0" * 64
            pointer_path.write_bytes(business.json_bytes(pointer))
            with self.assertRaisesRegex(ValueError, "pointer hash"):
                business.validate_snapshot(root)


class CompanyCaptureTests(unittest.TestCase):
    def response(self, payload=b"ok", length=None):
        response = MagicMock()
        response.headers = {"Content-Length": str(len(payload) if length is None else length)}
        response.read.return_value = payload
        response.__enter__.return_value = response
        return response

    def test_transient_500_retries_same_url_then_succeeds(self):
        url = "https://api.github.com/repos/" + business.REPO + "/git/trees/" + "a" * 40
        opener = MagicMock()
        opener.open.side_effect = [HTTPError(url, 500, "Transient", {}, None), self.response()]
        with patch.object(business, "build_opener", return_value=opener), patch.object(business.time, "sleep") as sleep:
            self.assertEqual(business.fetch_bytes(url, 100, "secret"), b"ok")
        self.assertEqual(opener.open.call_count, 2)
        self.assertTrue(all(call.args[0].full_url == url for call in opener.open.call_args_list))
        sleep.assert_called_once_with(1)

    def test_retry_attempts_are_bounded_and_retry_after_is_capped(self):
        url = "https://api.github.com/repos/" + business.REPO
        opener = MagicMock()
        opener.open.side_effect = [HTTPError(url, 429, "Busy", {"Retry-After": "999"}, None), URLError("temporary"), TimeoutError("temporary")]
        with patch.object(business, "build_opener", return_value=opener), patch.object(business.time, "sleep") as sleep:
            with self.assertRaises(TimeoutError):
                business.fetch_bytes(url, 100)
        self.assertEqual(opener.open.call_count, business.MAX_HTTP_ATTEMPTS)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [10, 2])

    def test_permanent_http_or_oversize_does_not_retry(self):
        url = "https://api.github.com/repos/" + business.REPO
        for value, error in [(HTTPError(url, 404, "Absent", {}, None), HTTPError), (self.response(length=101), ValueError)]:
            opener = MagicMock()
            if isinstance(value, Exception):
                opener.open.side_effect = value
            else:
                opener.open.return_value = value
            with patch.object(business, "build_opener", return_value=opener), patch.object(business.time, "sleep") as sleep:
                with self.assertRaises(error):
                    business.fetch_bytes(url, 100)
            self.assertEqual(opener.open.call_count, 1)
            sleep.assert_not_called()

    def test_raw_request_never_receives_authorization_even_if_token_supplied(self):
        opener = MagicMock()
        opener.open.return_value = self.response()
        with patch.object(business, "build_opener", return_value=opener):
            business.fetch_bytes("https://raw.githubusercontent.com/example/file.csv", 100, "secret")
        self.assertIsNone(opener.open.call_args.args[0].get_header("Authorization"))

    def test_capture_walks_pinned_directories_and_numeric_parts_without_recursion(self):
        import hashlib
        commit, first, second = "a" * 40, "b" * 40, "c" * 40
        api = "https://api.github.com/repos/" + business.REPO
        payload = b"a,b\n"
        blob = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
        files = [{"path": "registry_agency_data_mega" + (f"_part{i}" if i > 1 else "") + ".csv", "type": "blob", "mode": "100644", "sha": blob, "size": len(payload)} for i in range(12, 0, -1)]
        trees = {
            api + "/git/trees/" + commit: {"sha": "d" * 40, "truncated": False, "tree": [{"path": "registry_agency_scraper", "type": "tree", "mode": "040000", "sha": first}]},
            api + "/git/trees/" + first: {"sha": first, "truncated": False, "tree": [{"path": "registry_agency_outputs", "type": "tree", "mode": "040000", "sha": second}]},
            api + "/git/trees/" + second: {"sha": second, "truncated": False, "tree": files},
        }
        def fetch(url, limit, token=None):
            self.assertNotIn("recursive", url)
            if url in trees:
                self.assertEqual(token, "api-secret")
                return json.dumps(trees[url]).encode()
            self.assertTrue(url.startswith("https://raw.githubusercontent.com/" + business.REPO + "/" + commit + "/" + business.SOURCE_PATH + "/"))
            self.assertIsNone(token)
            return payload
        with tempfile.TemporaryDirectory() as temporary, patch.object(business, "fetch_bytes", side_effect=fetch) as mocked:
            _, source = business.capture_source(Path(temporary), commit, "api-secret")
        self.assertEqual([business.part_number(item["name"]) for item in source["files"]], list(range(1, 13)))
        self.assertEqual(mocked.call_count, 15)
        self.assertEqual(source["commit"], commit)

    def test_truncated_tree_fails_closed(self):
        malformed = json.dumps({"sha": "a" * 40, "truncated": True, "tree": []}).encode()
        with patch.object(business, "fetch_bytes", return_value=malformed) as mocked:
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                business.source_entries("https://api.github.com/repos/" + business.REPO, "a" * 40, None)
        self.assertEqual(mocked.call_count, 1)


@unittest.skipUnless(importlib.util.find_spec("shapely"), "Optional boundary geometry dependencies are absent")
class RepresentativePointTests(unittest.TestCase):
    class IdentityTransform:
        def transform(self, x, y, errcheck=True):
            return x, y

    def test_point_is_inside_actual_polygon_and_outside_its_hole(self):
        from shapely.geometry import Point, shape
        polygon = {"type": "Polygon", "coordinates": [[[23.3, 42.7], [23.32, 42.7], [23.32, 42.72], [23.3, 42.72], [23.3, 42.7]], [[23.305, 42.705], [23.305, 42.715], [23.315, 42.715], [23.315, 42.705], [23.305, 42.705]]]}
        point, identity = business.parcel_representative_point(polygon, self.IdentityTransform())
        self.assertTrue(shape(polygon).contains(Point(point["lng"], point["lat"])))
        self.assertRegex(identity, r"^[a-f0-9]{64}$")
        # A centroid lies in this hole; the chosen interior point must differ.
        self.assertFalse(shape(polygon).contains(shape(polygon).centroid))

    def test_disconnected_multipolygon_point_belongs_to_one_component(self):
        from shapely.geometry import Point, shape
        polygon = {"type": "MultiPolygon", "coordinates": [[[[23.3, 42.7], [23.31, 42.7], [23.31, 42.71], [23.3, 42.71], [23.3, 42.7]]], [[[23.4, 42.7], [23.42, 42.7], [23.42, 42.72], [23.4, 42.72], [23.4, 42.7]]]]}
        point, _ = business.parcel_representative_point(polygon, self.IdentityTransform())
        self.assertTrue(shape(polygon).contains(Point(point["lng"], point["lat"])))

    def test_invalid_self_intersecting_geometry_is_not_repaired(self):
        polygon = {"type": "Polygon", "coordinates": [[[23.3, 42.7], [23.32, 42.72], [23.32, 42.7], [23.3, 42.72], [23.3, 42.7]]]}
        with self.assertRaisesRegex(ValueError, "invalid_native"):
            business.parcel_representative_point(polygon, self.IdentityTransform())


if __name__ == "__main__":
    unittest.main()
