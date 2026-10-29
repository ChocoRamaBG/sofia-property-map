"""Enriched recovery may reuse fresh facts, never altered source prices."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from types import SimpleNamespace

from imot_enrichment import analyze_text, enrich_capture, property_features, seller_claim
import recover_imot_enriched_capture as recovery


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def stamp(value):
    return value.isoformat(timespec='seconds').replace('+00:00', 'Z')


def fixtures():
    now = datetime.now(timezone.utc)
    checked = stamp(now - timedelta(minutes=15))
    rows = []
    for index in (1, 2):
        identifier = f'1a{index:012}'
        row = dict(id=identifier, url=f'https://www.imot.bg/obiava-{identifier}-test',
                   neighborhood_bg='Neighbor 0', type_bg='2-СТАЕН', price=100000,
                   price_currency='EUR', vat_basis='included', area_sqm=80,
                   observed_at=checked, last_modified_at=None, construction_year=2015,
                   construction_label_bg='Тухла, 2015 г.', floor_bg='2 от 5',
                   enrichment_card_sha256='a' * 64,
                   **seller_claim(False, '', checked),
                   **analyze_text('', source='card', checked_at=checked, area_sqm=80))
        row['agency'] = None
        row['property_features'] = property_features('', checked_at=checked, completion_label='Тухла, 2015 г.', floor_label='2 от 5')
        rows.append(row)
    searches = []
    kinds = [('dvustaen', '2-СТАЕН'), ('tristaen', '3-СТАЕН'), ('chetiristaen', '4-СТАЕН')]
    for neighbor in range(60):
        for slug, label in kinds:
            identifiers = [row['id'] for row in rows] if neighbor == 0 and slug == 'dvustaen' else []
            searches.append(dict(key=f'n{neighbor}:{slug}:0-open', expected_count=len(identifiers), captured_count=len(identifiers),
                                 neighborhood_bg=f'Neighbor {neighbor}', type_bg=label,
                                 pages=[dict(count=len(identifiers), ids=identifiers, ids_sha256=hashlib.sha256(encoded(identifiers)).hexdigest())]))
    raw = dict(version=1, capture=dict(source='imot.bg', source_url=recovery.SOURCE_CATALOGUE,
               started_at=stamp(now - timedelta(minutes=20)), finished_at=stamp(now - timedelta(minutes=10)),
               complete=True, expected_count=2, captured_count=2, requested_neighborhood_count=60, captured_neighborhood_count=60,
               scope=dict(transaction='sale', types=['2-СТАЕН', '3-СТАЕН', '4-СТАЕН'], construction_year_min=None),
               neighborhoods=[dict(key=f'n{i}') for i in range(60)], searches=searches), listings=rows)
    enriched, _, _ = enrich_capture(raw, limit=0)
    return raw, enriched


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.enriched = fixtures()

    def validate(self):
        return recovery.validate_enriched_capture(encoded(self.raw), encoded(self.enriched))

    def test_fresh_completed_capture_preserves_source_times_and_ids(self):
        context, report = self.validate()
        self.assertEqual(context['captured_count'], 2)
        self.assertEqual(context['finished_at'], self.raw['capture']['finished_at'])
        self.assertEqual(report['pending_count'], 2)

    def test_expired_or_future_capture_cannot_be_retimed(self):
        for age in (timedelta(hours=7), timedelta(hours=-1)):
            self.raw, self.enriched = fixtures()
            self.raw['capture']['finished_at'] = stamp(datetime.now(timezone.utc) - age)
            self.enriched['capture'] = copy.deepcopy(self.raw['capture'])
            with self.subTest(age=age), self.assertRaises(ValueError): self.validate()

    def test_enrichment_cannot_change_price_identity_or_timestamp(self):
        for key, value in [('price', 90000), ('id', '1a999999999999'), ('observed_at', '2026-01-01T00:00:00Z')]:
            self.raw, self.enriched = fixtures()
            self.enriched['listings'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.validate()

    def test_enrichment_cannot_rewrite_source_completeness(self):
        self.enriched['capture']['complete'] = False
        with self.assertRaises(ValueError): self.validate()

    def test_page_id_hash_and_exact_union_are_required(self):
        self.raw['capture']['searches'][0]['pages'][0]['ids_sha256'] = '0' * 64
        self.enriched['capture'] = copy.deepcopy(self.raw['capture'])
        with self.assertRaises(ValueError): self.validate()

    def test_neighborhood_and_type_evidence_must_match_listing(self):
        self.raw['capture']['searches'][0]['neighborhood_bg'] = 'Different'
        self.enriched['capture'] = copy.deepcopy(self.raw['capture'])
        with self.assertRaises(ValueError): self.validate()

    def test_coverage_counts_cannot_overstate_features(self):
        self.enriched['enrichment']['professional_contact_count'] += 1
        with self.assertRaises(ValueError): self.validate()

    def test_unsupported_claims_and_raw_description_are_rejected(self):
        self.enriched['listings'][0]['analysis']['raw_description'] = 'must not survive'
        with self.assertRaises(ValueError): self.validate()
        self.raw, self.enriched = fixtures()
        self.enriched['listings'][0]['location_hints'] = [dict(kind='street', name='test', nearby=False, source='description', house_number=None, phone='forbidden')]
        with self.assertRaises(ValueError): self.validate()

    def test_old_cache_schema_or_foreign_listing_is_rejected(self):
        self.enriched['enrichment_cache']['foreign'] = {'version': 2, 'raw_description': 'forbidden'}
        with self.assertRaises(ValueError): self.validate()

    def test_method_version_must_be_current(self):
        self.enriched['listings'][0]['analysis_method_version'] = 2
        with self.assertRaises(ValueError): self.validate()

    def test_only_safe_exact_zip_members_are_read(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('capture.json', encoded(self.raw))
            zipped.writestr('capture-enriched.json', encoded(self.enriched))
        raw, enriched = recovery.read_evidence_zip(archive.getvalue())
        self.assertEqual(raw, encoded(self.raw)); self.assertEqual(enriched, encoded(self.enriched))
        for name in ['../capture.json', 'script.py', 'nested/capture-enriched.json']:
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('capture.json', encoded(self.raw)); zipped.writestr('capture-enriched.json', encoded(self.enriched)); zipped.writestr(name, '{}')
            with self.subTest(name=name), self.assertRaises(ValueError): recovery.read_evidence_zip(archive.getvalue())

    def test_artifact_digest_is_required_and_storage_get_has_no_token(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('capture.json', encoded(self.raw)); zipped.writestr('capture-enriched.json', encoded(self.enriched))
        payload = archive.getvalue()
        artifact = dict(id=123, size_in_bytes=len(payload), digest='sha256:' + hashlib.sha256(payload).hexdigest())
        session = unittest.mock.Mock()
        session.get.return_value = SimpleNamespace(status_code=302, headers={'Location': 'https://test.blob.core.windows.net/artifact'})
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response; response.status_code = 200; response.headers = {}; response.iter_content.return_value = [payload]
        with patch.object(recovery.requests, 'get', return_value=response) as storage_get:
            self.assertEqual(recovery.download_evidence(session, artifact)[0], encoded(self.raw))
            self.assertNotIn('headers', storage_get.call_args.kwargs)
            self.assertNotIn('auth', storage_get.call_args.kwargs)
        artifact['digest'] = 'sha256:' + '0' * 64
        with patch.object(recovery.requests, 'get', return_value=response):
            with self.assertRaises(ValueError): recovery.download_evidence(session, artifact)
        artifact.pop('digest')
        with self.assertRaises(ValueError): recovery.download_evidence(session, artifact)

    def test_untrusted_storage_redirect_is_never_followed(self):
        session = unittest.mock.Mock()
        session.get.return_value = SimpleNamespace(status_code=302, headers={'Location': 'https://attacker.example/artifact'})
        with patch.object(recovery.requests, 'get') as storage_get:
            with self.assertRaises(ValueError): recovery.download_evidence(session, dict(id=1, size_in_bytes=20, digest='sha256:' + 'a' * 64))
            storage_get.assert_not_called()

    def origin(self):
        run_id = 123
        run = dict(id=run_id, status='completed', conclusion='failure', path=recovery.WORKFLOW_PATH,
                   head_branch='main', head_sha='a' * 40, event='schedule',
                   head_repository=dict(full_name=recovery.REPOSITORY), repository=dict(full_name=recovery.REPOSITORY))
        capture = dict(name=recovery.CAPTURE_STEP, conclusion='success', started_at='2026-10-29T10:00:00Z', completed_at='2026-10-29T10:30:00Z')
        enrichment = dict(name=recovery.ENRICHMENT_STEP, conclusion='success', started_at='2026-10-29T10:30:00Z', completed_at='2026-10-29T11:00:00Z')
        jobs = dict(jobs=[dict(run_id=run_id, steps=[capture, enrichment])])
        artifact = dict(name=f'imot-source-evidence-{run_id}', expired=False, workflow_run=dict(id=run_id, head_sha='a' * 40))
        return run, jobs, artifact, run_id

    def test_failed_build_is_eligible_only_when_capture_and_enrichment_succeeded(self):
        args = self.origin()
        self.assertEqual(len(recovery.validate_origin(*args)), 2)
        args[1]['jobs'][0]['steps'][1]['conclusion'] = 'failure'
        with self.assertRaises(ValueError): recovery.validate_origin(*args)

    def test_other_repo_branch_or_revision_cannot_supply_enriched_evidence(self):
        for field, value in [('head_branch', 'untrusted'), ('head_sha', None), ('repository', dict(full_name='other/repo'))]:
            args = self.origin(); args[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): recovery.validate_origin(*args)
        args = self.origin(); args[2]['workflow_run']['head_sha'] = 'b' * 40
        with self.assertRaises(ValueError): recovery.validate_origin(*args)

    def test_same_or_existing_output_paths_never_overwrite_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'same.json'
            with self.assertRaises(ValueError): recovery.write_outputs(path, b'enriched', path, b'raw')
            self.assertFalse(path.exists())
            path.write_bytes(b'existing')
            with self.assertRaises(ValueError): recovery.write_outputs(path, b'new')
            self.assertEqual(path.read_bytes(), b'existing')

    def test_distinct_outputs_preserve_exact_validated_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recovery.write_outputs(root / 'enriched.json', b'enriched', root / 'raw.json', b'raw')
            self.assertEqual((root / 'enriched.json').read_bytes(), b'enriched')
            self.assertEqual((root / 'raw.json').read_bytes(), b'raw')

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaises(ValueError): recovery.strict_json(b'{"version":1,"version":1}')


if __name__ == '__main__': unittest.main()
