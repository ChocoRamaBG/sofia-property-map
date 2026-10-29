"""Publication safeguards for source membership changes, without hosting access."""
import copy
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

import deploy_boundary_ftps as deploy

IDS = {'68134.1.1', '68134.1.2', '68134.1.3'}


class CataloguePublicationTests(unittest.TestCase):
    def test_cadastral_publisher_has_no_excel_dependency(self):
        script = Path(__file__).with_name('deploy_cadastre_ftps.py')
        result = subprocess.run([sys.executable, '-S', str(script), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='sofia-catalogue-publish-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'previous.json'
        self.manifest = {'snapshot_id': 'a' * 32, 'parcel_count': 2, 'ambiguous_parcel_count': 1}

    def state(self):
        descriptor = deploy.write_previous_ids(self.path, IDS)
        self.path.write_text(json.dumps({'catalogue_ids': descriptor}))
        return descriptor

    def test_exact_sorted_previous_membership_is_verified(self):
        self.state()
        self.assertEqual(deploy.previous_ids(self.path, self.manifest), IDS)

    def test_legacy_envelope_cannot_infer_changes(self):
        self.path.write_text('{}')
        self.assertIsNone(deploy.previous_ids(self.path, self.manifest))

    def test_tampered_sidecar_or_count_stops_comparison(self):
        descriptor = self.state()
        (self.root / descriptor['file']).write_bytes(b'68134.1.9\n')
        with self.assertRaises(ValueError): deploy.previous_ids(self.path, self.manifest)

    def test_sidecar_path_cannot_escape_envelope_directory(self):
        self.path.write_text(json.dumps({'catalogue_ids': {'file': '../outside.ids', 'bytes': 0, 'sha256': '', 'rows': 0}}))
        with self.assertRaises(ValueError): deploy.previous_ids(self.path, self.manifest)

    def test_membership_changes_preserve_history_meaning(self):
        candidate = dict(snapshot_id='b' * 32, captured_at='2026-10-29T10:00:00Z')
        with patch.object(deploy, 'catalogue_ids', return_value={'68134.1.2', '68134.1.3', '68134.1.4', '68134.1.5'}):
            result = deploy.catalogue_changes(self.root, candidate, self.manifest, IDS)
        self.assertEqual((result['new_to_snapshot_count'], result['not_in_latest_snapshot_count'], result['unchanged_count']), (2, 1, 2))
        self.assertEqual(result['new_identifiers_preview'], ['68134.1.4', '68134.1.5'])
        self.assertEqual(result['absent_identifiers_preview'], ['68134.1.1'])
        self.assertIn('absence does not establish legal cancellation', result['interpretation'])

    def test_first_capture_is_not_reported_as_newly_created_parcels(self):
        candidate = dict(snapshot_id='b' * 32, captured_at='2026-10-29T10:00:00Z')
        with patch.object(deploy, 'catalogue_ids', return_value=IDS):
            result = deploy.catalogue_changes(self.root, candidate, None, None)
        self.assertFalse(result['comparison_available'])
        self.assertIsNone(result['new_to_snapshot_count'])
        self.assertIsNone(result['not_in_latest_snapshot_count'])

    def test_previous_remote_payload_must_match_manifest_hash(self):
        manifest = {'version': 2, 'snapshot_id': 'a' * 32,
                    'catalogue': {'file': 'catalogue.tsv', 'bytes': 3, 'sha256': deploy.digest(b'abc')}}
        with patch.object(deploy, 'read_remote', return_value=b'bad'):
            with self.assertRaises(ValueError): deploy.fetch_catalogue_ids(object(), manifest)

    def test_new_catalogue_cannot_activate_before_reader_upgrade(self):
        with patch.object(deploy, 'read_remote', return_value=b'<?php // legacy reader'):
            with self.assertRaises(ValueError): deploy.verify_catalogue_readers(object())

    def test_capture_regression_or_large_drop_stops_publication(self):
        previous = dict(captured_at='2026-10-28T10:00:00Z', parcel_count=1000, ambiguous_parcel_count=1,
                        sources=[dict(source_url='https://kais.cadastre.bg/example', captured_at='2026-10-28T10:00:00Z', record_count=1001)])
        for changes in [dict(captured_at='2026-10-27T10:00:00Z'), dict(parcel_count=799)]:
            candidate = copy.deepcopy(previous); candidate.update(changes)
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError): deploy.continuity(previous, candidate)


if __name__ == '__main__': unittest.main()
