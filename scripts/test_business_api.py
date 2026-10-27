"""HTTP fixtures for the standalone PHP business API; never reads real data."""
from __future__ import annotations

import hashlib
import argparse
import json
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PHP = shutil.which("php")
API = Path(__file__).resolve().parents[1] / "public" / "business-data.php"
CID = "68134.100.100"
STAMP = "2026-10-27T10:00:00+00:00"


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fake_uic(number: int) -> str:
    prefix = str(90_000_000 + number)
    digits = list(map(int, prefix))
    check = sum((i + 1) * value for i, value in enumerate(digits)) % 11
    if check == 10:
        check = sum((i + 3) * value for i, value in enumerate(digits)) % 11
        if check == 10:
            check = 0
    return prefix + str(check)


def verify_prepared_snapshot(snapshot_root: Path) -> None:
    """Check the real producer/API contract in an isolated copied docroot."""
    if PHP is None:
        raise RuntimeError("PHP is required to verify a prepared business snapshot")
    from refresh_business_addresses import validate_snapshot
    manifest = validate_snapshot(snapshot_root)
    snapshot_id = manifest["snapshot_id"]
    source = snapshot_root / "business-snapshots" / snapshot_id
    if snapshot_root.is_symlink() or source.is_symlink() or any(path.is_symlink() for path in source.iterdir()):
        raise ValueError("Prepared verification snapshot may not contain symlinks")
    parcel_index = json.loads((source / "parcel-index.json").read_bytes())
    if "points_index" in manifest:
        points = json.loads((source / "points-index.json").read_bytes())
        cadastral_id = next(iter(points)) if points else next(iter(parcel_index))
        shard_name = parcel_index[cadastral_id]
    else:
        cadastral_id, shard_name = next(iter(parcel_index.items()))
    companies = json.loads((source / shard_name).read_bytes())[cadastral_id]
    uic = companies[0]["uic"]
    with tempfile.TemporaryDirectory(prefix="sofia-business-real-api-") as temporary:
        root = Path(temporary)
        private = root / "private"
        private.mkdir()
        shutil.copyfile(API, root / "business-data.php")
        shutil.copyfile(snapshot_root / "business-active.json", private / "business-active.json")
        destination = private / "business-snapshots" / snapshot_id
        shutil.copytree(source, destination, symlinks=False)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}
        process = subprocess.Popen([PHP, "-S", f"127.0.0.1:{port}", "-t", str(root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
        url = f"http://127.0.0.1:{port}/business-data.php"
        def request(params):
            try:
                with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params), timeout=15) as response:
                    body = response.read(2 * 1024 * 1024)
                    if len(body) >= 2 * 1024 * 1024:
                        raise ValueError("Prepared API verification response exceeds its limit")
                    data = json.loads(body)
            except urllib.error.HTTPError as error:
                raise ValueError(f"Prepared business snapshot failed PHP API validation (HTTP {error.code})") from None
            if data.get("status") != "available" or data.get("snapshot_id") != snapshot_id:
                raise ValueError("Prepared PHP API response does not match the validated snapshot")
            return data
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Prepared PHP verification server exited")
                try:
                    metadata = request({"action": "meta"})
                    break
                except urllib.error.URLError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("Prepared PHP verification server did not start")
            if metadata.get("counts") != manifest["counts"] or metadata.get("source") != manifest["source"] or metadata.get("cadastre") != manifest["cadastre"]:
                raise ValueError("Prepared PHP metadata and builder metadata differ")
            plot = request({"action": "plot", "id": cadastral_id})
            if plot.get("total") != len(companies) or not any(company.get("uic") == uic for company in plot.get("companies", [])):
                raise ValueError("Prepared PHP plot response differs from its immutable shard")
            search = request({"action": "search", "q": uic})
            if not any(row.get("uic") == uic and row.get("cadastral_id") == cadastral_id for row in search.get("results", [])):
                raise ValueError("Prepared PHP company search did not find the matched parcel")
            if "points_index" in manifest:
                viewport = request({"action": "viewport", "north": 43.1, "south": 42.4, "east": 24, "west": 22.8, "zoom": 10})
                if viewport.get("total") != manifest["counts"]["mapped_business_parcels"] or viewport.get("company_total") != manifest["counts"]["mapped_companies"]:
                    raise ValueError("Prepared PHP map coverage differs from the validated point index")
                represented = sum(item.get("count", 1) for item in viewport.get("items", []))
                if represented != viewport["total"] or sum(item["company_count"] for item in viewport["items"]) != viewport["company_total"] or viewport.get("truncated"):
                    raise ValueError("Prepared PHP map aggregation omits matched records")
            print(f"Verified real PHP API metadata, plot, EIK search and optional map coverage for {manifest['counts']['matched_companies']:,} prepared company associations; no source rows printed")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@unittest.skipUnless(PHP, "PHP is unavailable; the CI job must execute these HTTP fixtures")
class BusinessApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="sofia-business-api-")
        cls.root = Path(cls.temporary.name)
        shutil.copyfile(API, cls.root / "business-data.php")
        (cls.root / "private" / "business-snapshots").mkdir(parents=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}
        cls.server = subprocess.Popen([PHP, "-S", f"127.0.0.1:{cls.port}", "-t", str(cls.root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
        cls.base = f"http://127.0.0.1:{cls.port}/business-data.php"
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError("PHP fixture server exited before accepting requests")
            try:
                urllib.request.urlopen(cls.base, timeout=0.2).close()
                break
            except urllib.error.HTTPError:
                break  # An honest 503 without a pointer proves HTTP is ready.
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.05)
        else:
            cls.server.terminate()
            raise RuntimeError("PHP fixture server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)
        cls.temporary.cleanup()

    def setUp(self):
        self.fixture()

    def fixture(self, count=45, snapshot_id="1" * 32, mutate_company=None, extra_part=False, parcel_ids=None, points=None):
        private = self.root / "private"
        directory = private / "business-snapshots" / snapshot_id
        directory.mkdir(exist_ok=True)
        companies = []
        for number in range(count):
            uic = fake_uic(number)
            company = {"uic": uic, "name": ("ALPHA REALTY " if number == 0 else "") + f"Тест Имоти {number}",
                       "legal_form": "Дружество с ограничена отговорност", "activity": "", "registered_address": "гр. София, ул. тестова № 1",
                       "status": "not_verified", "as_of": "2026-10-25",
                       "source_url": f"https://portal.registryagency.bg/CR/Reports/ActiveConditionTabResult?uic={uic}"}
            if mutate_company:
                mutate_company(company, number)
            companies.append(company)
        parcel_ids = parcel_ids or [CID] * count
        self.assertEqual(len(parcel_ids), count)
        parcel = {cid: "companies-000.json" for cid in parcel_ids}
        grouped = {cid: [] for cid in parcel}
        for company, cid in zip(companies, parcel_ids):
            grouped[cid].append(company)
        search = [{key: company[key] for key in ("uic", "name", "registered_address")} | {"cadastral_id": cid} for company, cid in zip(companies, parcel_ids)]
        payloads = {"companies-000.json": encoded(grouped), "parcel-index.json": encoded(parcel), "search-index.json": encoded(search)}
        if points is not None:
            payloads["points-index.json"] = encoded(points)
        for name, payload in payloads.items():
            (directory / name).write_bytes(payload)
        def evidence(name):
            return {"bytes": len(payloads[name]), "sha256": sha(payloads[name])}
        files = [{"name": "registry_agency_data_mega.csv", "bytes": 134_217_728, "git_blob_sha1": "a" * 40, "sha256": "b" * 64}]
        if extra_part:
            files.append({"name": "registry_agency_data_mega_part10.csv", "bytes": 10, "git_blob_sha1": "c" * 40, "sha256": "d" * 64})
        self.manifest = {"version": 1, "snapshot_id": snapshot_id, "generated_at": STAMP,
                         "source": {"repo": "ChocoRamaBG/register-of-outpatient-care-facilities-and-hospices", "commit": "a" * 40,
                                    "path": "registry_agency_scraper/registry_agency_outputs", "files": files},
                         "cadastre": {"manifest_sha256": "c" * 64, "snapshot_id": "c" * 32, "captured_from": STAMP, "captured_to": STAMP,
                                      "sources": [{"code": f"sofia-district-{i:02d}", "source_url": f"https://kais.cadastre.bg/bg/OpenData/Download?path=fixture-{i}", "zip_sha256": "d" * 64, "captured_at": STAMP} for i in range(24)]},
                         "counts": {"matched_companies": count, "matched_parcels": len(parcel), "sofia_candidates": count},
                         "shards": {"companies-000.json": evidence("companies-000.json")},
                         "parcel_index": {"file": "parcel-index.json", **evidence("parcel-index.json")},
                         "search_index": {"file": "search-index.json", **evidence("search-index.json")}}
        if points is not None:
            mapped_companies = sum(1 for cid in parcel_ids if cid in points)
            self.manifest["points_index"] = {"file": "points-index.json", **evidence("points-index.json")}
            self.manifest["counts"].update({"mapped_business_parcels": len(points), "unmapped_business_parcels": len(parcel) - len(points),
                                            "mapped_companies": mapped_companies, "unmapped_companies": count - mapped_companies})
        self.directory = directory
        self.publish_manifest()
        return companies

    def publish_manifest(self):
        raw = encoded(self.manifest)
        (self.directory / "manifest.json").write_bytes(raw)
        self.pointer = {"version": 1, "snapshot_id": self.manifest["snapshot_id"], "manifest_sha256": sha(raw)}
        (self.root / "private" / "business-active.json").write_bytes(encoded(self.pointer))

    def request(self, params=None, method="GET"):
        query = "?" + urllib.parse.urlencode(params) if params else ""
        request = urllib.request.Request(self.base + query, method=method, data=b"" if method == "POST" else None)
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            self.assertIn("application/json", response.headers.get("Content-Type", ""))
            self.assertIn("no-store", response.headers.get("Cache-Control", ""))
            return response.code, json.loads(body) if body else None, response.headers

    def viewport(self, **overrides):
        return self.request({"action": "viewport", "north": 43.1, "south": 42.4, "east": 24, "west": 22.8, "zoom": 10, **overrides})

    def spread_fixture(self, count):
        ids = [f"68134.100.{i + 1}" for i in range(count)]
        points = {cid: {"lat": 42.5 + (i // 50) * 0.01, "lng": 23 + (i % 50) * 0.01} for i, cid in enumerate(ids)}
        self.fixture(count=count, parcel_ids=ids, points=points)
        return points

    def test_metadata_has_explicit_scope_and_separate_provenance(self):
        status, body, _ = self.request({"action": "meta"})
        self.assertEqual(status, 200)
        self.assertTrue(body["available"])
        self.assertEqual(body["counts"]["matched_companies"], 45)
        self.assertEqual(body["scope"], "registered_office_address_association")
        self.assertEqual(body["coverage"]["source"]["commit"], "a" * 40)
        self.assertEqual(body["coverage"]["cadastre"]["captured_from"], STAMP)
        self.assertNotIn("companies", body)

    def test_plot_pagination_is_bounded_and_consistent(self):
        status, first, _ = self.request({"action": "plot", "id": CID})
        status2, second, _ = self.request({"action": "plot", "id": CID, "offset": 20, "limit": 20})
        status3, final, _ = self.request({"action": "plot", "id": CID, "offset": 40, "limit": 20})
        self.assertEqual((status, status2, status3), (200, 200, 200))
        self.assertEqual((len(first["companies"]), len(second["companies"]), len(final["companies"])), (20, 20, 5))
        self.assertEqual(first["total"], 45)
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertTrue(second["has_more"])
        self.assertFalse(final["has_more"])
        self.assertTrue({c["uic"] for c in first["companies"]}.isdisjoint(c["uic"] for c in second["companies"]))

    def test_unmatched_parcel_is_not_an_ownership_assertion(self):
        status, body, _ = self.request({"action": "plot", "id": "68134.200.200"})
        self.assertEqual(status, 200)
        self.assertEqual(body["companies"], [])
        self.assertEqual(body["total"], 0)
        self.assertEqual(body["coverage"]["counts"]["matched_parcels"], 1)

    def test_search_casefolds_english_cyrillic_and_uic(self):
        for query in ("alpha realty", "ТЕСТ ИМОТИ", fake_uic(0)):
            with self.subTest(query=query):
                status, body, _ = self.request({"action": "search", "q": query})
                self.assertEqual(status, 200)
                self.assertGreater(body["total"], 0)
                self.assertEqual(body["results"][0]["cadastral_id"], CID)
                self.assertEqual(set(body["results"][0]), {"uic", "name", "registered_address", "cadastral_id"})
                self.assertLessEqual(len(body["results"]), 40)
        _, body, _ = self.request({"action": "search", "q": "ТЕСТ ИМОТИ"})
        self.assertEqual(body["total"], 45)
        self.assertTrue(body["truncated"])

    def test_streaming_search_spans_multiple_read_chunks(self):
        self.fixture(count=700)
        self.assertGreater((self.directory / "search-index.json").stat().st_size, 65536)
        status, body, _ = self.request({"action": "search", "q": "ТЕСТ"})
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 700)
        self.assertEqual(len(body["results"]), 40)

    def test_invalid_ids_actions_queries_and_limits_are_rejected(self):
        cases = [{"action": "plot", "id": "../../private/config.php"}, {"action": "plot", "id[]": CID},
                 {"action": "plot", "id": CID, "limit": 51}, {"action": "search", "q": "а"},
                 {"action": "search", "q": "a" * 121}, {"action": "search", "q": "Тест", "limit": 41}, {"action": "write"}]
        for params in cases:
            with self.subTest(params=params):
                status, body, _ = self.request(params)
                self.assertEqual(status, 400)
                self.assertFalse(body["available"])

    def test_post_is_rejected_and_head_has_no_body(self):
        status, body, headers = self.request({"action": "meta"}, method="POST")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "GET, HEAD")
        self.assertEqual(body["status"], "invalid_request")
        status, body, _ = self.request({"action": "meta"}, method="HEAD")
        self.assertEqual(status, 200)
        self.assertIsNone(body)

    def test_corrupted_hashes_fail_honestly(self):
        for filename, params in [("manifest.json", {"action": "meta"}), ("parcel-index.json", {"action": "plot", "id": CID}),
                                 ("companies-000.json", {"action": "plot", "id": CID}), ("search-index.json", {"action": "search", "q": "Тест"})]:
            with self.subTest(filename=filename):
                self.fixture()
                path = self.directory / filename
                original = path.read_bytes()
                path.write_bytes(b" " + original[1:])  # Same size, different digest.
                status, body, _ = self.request(params)
                self.assertEqual(status, 503)
                self.assertEqual(body["status"], "unavailable")
                self.assertIsNone(body["total"])

    def test_missing_or_unsafe_pointer_is_unavailable(self):
        path = self.root / "private" / "business-active.json"
        path.unlink()
        status, body, _ = self.request()
        self.assertEqual(status, 503)
        self.assertIsNone(body["total"])
        path.write_bytes(encoded({"version": 1, "snapshot_id": "../../outside", "manifest_sha256": "a" * 64}))
        status, _, _ = self.request()
        self.assertEqual(status, 503)

    def test_extra_private_company_fields_are_rejected_even_with_valid_hashes(self):
        self.fixture(mutate_company=lambda company, _: company.update({"owners": "fixture-only prohibited field"}))
        status, body, _ = self.request({"action": "plot", "id": CID})
        self.assertEqual(status, 503)
        self.assertEqual(body["companies"], [])

    def test_untrusted_profile_url_is_rejected(self):
        self.fixture(mutate_company=lambda company, _: company.update({"source_url": "https://example.invalid/profile"}))
        status, _, _ = self.request({"action": "plot", "id": CID})
        self.assertEqual(status, 503)

    def test_unknown_source_date_is_preserved(self):
        self.fixture(mutate_company=lambda company, _: company.update({"as_of": ""}))
        status, body, _ = self.request({"action": "plot", "id": CID})
        self.assertEqual(status, 200)
        self.assertEqual(body["companies"][0]["as_of"], "")

    def test_future_part_names_and_host_byte_limit_are_supported(self):
        self.fixture(extra_part=True)
        status, body, _ = self.request({"action": "meta"})
        self.assertEqual(status, 200)
        self.assertEqual(body["source"]["files"][1]["name"], "registry_agency_data_mega_part10.csv")

    def test_inactive_snapshot_cannot_change_an_active_page(self):
        old_pointer = encoded(self.pointer)
        self.fixture(count=46, snapshot_id="2" * 32)
        new_pointer = encoded(self.pointer)
        (self.root / "private" / "business-active.json").write_bytes(old_pointer)
        status, old, _ = self.request({"action": "plot", "id": CID})
        self.assertEqual(status, 200)
        self.assertEqual((old["snapshot_id"], old["total"]), ("1" * 32, 45))
        (self.root / "private" / "business-active.json").write_bytes(new_pointer)
        status, new, _ = self.request({"action": "plot", "id": CID})
        self.assertEqual(status, 200)
        self.assertEqual((new["snapshot_id"], new["total"]), ("2" * 32, 46))

    def test_viewport_counts_two_companies_on_one_parcel_once(self):
        second = "68134.200.200"
        points = {CID: {"lat": 42.7, "lng": 23.3}, second: {"lat": 42.8, "lng": 23.4}}
        self.fixture(count=3, parcel_ids=[CID, CID, second], points=points)
        status, body, _ = self.viewport(zoom=18)
        self.assertEqual(status, 200)
        self.assertEqual((body["total"], body["company_total"]), (2, 3))
        self.assertTrue(body["complete"])
        self.assertFalse(body["truncated"])
        self.assertEqual({row["cadastral_id"]: row["company_count"] for row in body["items"]}, {CID: 2, second: 1})
        self.assertTrue(all(row["kind"] == "point" and row["location_method"] == "official_parcel_representative_point" for row in body["items"]))
        self.assertEqual(body["query"], "")

    def test_viewport_full_matching_bounds_do_not_shrink_to_current_view(self):
        second = "68134.200.200"
        self.fixture(count=2, parcel_ids=[CID, second], points={CID: {"lat": 42.7, "lng": 23.3}, second: {"lat": 42.8, "lng": 23.4}})
        status, body, _ = self.viewport(north=42.71, south=42.69, east=23.31, west=23.29, zoom=18)
        self.assertEqual(status, 200)
        self.assertEqual((body["total"], body["matching_total"]), (1, 2))
        self.assertLessEqual(body["bounds"]["south"], 42.7)
        self.assertGreaterEqual(body["bounds"]["north"], 42.8)
        self.assertGreaterEqual(body["bounds"]["east"], 23.4)

    def test_viewport_search_includes_matches_beyond_forty_result_preview(self):
        self.spread_fixture(60)
        _, preview, _ = self.request({"action": "search", "q": "ТЕСТ"})
        status, body, _ = self.viewport(q="  ТЕСТ  ", zoom=18)
        self.assertEqual(status, 200)
        self.assertEqual((len(preview["results"]), preview["total"]), (40, 60))
        self.assertEqual((body["total"], body["company_total"], len(body["items"])), (60, 60, 60))
        self.assertEqual(body["query"], "ТЕСТ")
        status, one, _ = self.viewport(q=fake_uic(59), zoom=18)
        self.assertEqual(status, 200)
        self.assertEqual((one["total"], one["company_total"]), (1, 1))
        status, none, _ = self.viewport(q="absent fixture company", zoom=18)
        self.assertEqual(status, 200)
        self.assertEqual(none["items"], [])
        self.assertEqual(none["total"], 0)
        self.assertIsNone(none["bounds"])

    def test_viewport_clusters_are_complete_and_split_progressively(self):
        self.spread_fixture(200)
        status, broad, _ = self.viewport(zoom=4)
        status2, close, _ = self.viewport(zoom=13)
        self.assertEqual((status, status2), (200, 200))
        self.assertEqual(sum(item["count"] for item in broad["items"]), 200)
        self.assertEqual(sum(item["count"] for item in close["items"]), 200)
        self.assertEqual(sum(item["company_count"] for item in close["items"]), 200)
        self.assertGreater(len(close["items"]), len(broad["items"]))
        for item in close["items"]:
            self.assertEqual(item["kind"], "cluster")
            self.assertLessEqual(item["bounds"]["south"], item["lat"])
            self.assertGreaterEqual(item["bounds"]["north"], item["lat"])

    def test_viewport_dense_high_zoom_coarsens_without_dropping_points(self):
        self.spread_fixture(1250)
        status, body, _ = self.viewport(zoom=22)
        self.assertEqual(status, 200)
        self.assertLessEqual(len(body["items"]), 1200)
        self.assertEqual(sum(item["count"] for item in body["items"]), 1250)
        self.assertEqual(sum(item["company_count"] for item in body["items"]), 1250)
        self.assertEqual(body["total"], 1250)
        self.assertLess(body["cluster_zoom"], 22)
        self.assertFalse(body["truncated"])

    def test_viewport_rejects_bad_bounds_zoom_and_query(self):
        self.spread_fixture(2)
        for overrides in [{"north": "NaN"}, {"south": 43.1}, {"east": 20}, {"north": 91}, {"west": -181}, {"zoom": 23}, {"zoom": "Infinity"}, {"q": "а"}, {"q[]": "alpha"}]:
            with self.subTest(overrides=overrides):
                status, _, _ = self.viewport(**overrides)
                self.assertEqual(status, 400)
        status, body, _ = self.viewport(q="   ", north="43.100000000000001", south="42.400000000000001")
        self.assertEqual(status, 200)
        self.assertEqual(body["query"], "")

    def test_viewport_point_hash_and_schema_are_verified(self):
        self.spread_fixture(2)
        path = self.directory / "points-index.json"
        raw = path.read_bytes()
        path.write_bytes(b" " + raw[1:])
        status, body, _ = self.viewport()
        self.assertEqual(status, 503)
        self.assertIsNone(body["total"])
        for bad in [{"lat": 0, "lng": 23.3}, {"lat": "42.7", "lng": 23.3}, {"lat": 42.7, "lng": 23.3, "owner": "prohibited"}]:
            with self.subTest(bad=bad):
                self.fixture(count=1, points={CID: bad})
                status, _, _ = self.viewport()
                self.assertEqual(status, 503)

    def test_viewport_point_coverage_must_match_company_index(self):
        self.spread_fixture(2)
        self.manifest["counts"]["mapped_companies"] = 1
        self.manifest["counts"]["unmapped_companies"] = 1
        self.publish_manifest()
        status, _, _ = self.viewport()
        self.assertEqual(status, 503)

    def test_unusable_geometry_is_explicit_unmapped_coverage(self):
        second = "68134.200.200"
        self.fixture(count=3, parcel_ids=[CID, CID, second], points={CID: {"lat": 42.7, "lng": 23.3}})
        status, body, _ = self.viewport(zoom=18)
        self.assertEqual(status, 200)
        self.assertEqual((body["total"], body["company_total"]), (1, 2))
        self.assertEqual(body["coverage"]["counts"]["unmapped_business_parcels"], 1)
        self.assertEqual(body["coverage"]["counts"]["unmapped_companies"], 1)

    def test_legacy_snapshot_remains_usable_except_for_map(self):
        status, body, _ = self.viewport()
        self.assertEqual(status, 503)
        self.assertIsNone(body["total"])
        for params in [{"action": "meta"}, {"action": "plot", "id": CID}, {"action": "search", "q": "Тест"}]:
            with self.subTest(params=params):
                status, body, _ = self.request(params)
                self.assertEqual(status, 200)
                self.assertFalse(body["coverage"]["map_available"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--snapshot", type=Path)
    args, remaining = parser.parse_known_args()
    if args.snapshot is not None:
        if remaining:
            parser.error("--snapshot does not accept unittest selection arguments")
        verify_prepared_snapshot(args.snapshot)
    else:
        unittest.main(argv=[__file__, *remaining])
