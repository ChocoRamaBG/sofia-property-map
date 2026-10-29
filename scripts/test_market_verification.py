"""Readback freshness must come from the published capture, not a green UI check."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import imot_market as market
from test_imot_market import raw_offer, EmptyResolver
from verify_market_snapshot import verify_active_market

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


class FilesFTP:
    def __init__(self, files): self.files = files
    def nlst(self, path): return [name for name in self.files if name.startswith(path + '/')]
    def retrbinary(self, command, callback): callback(self.files[command.removeprefix('RETR ')])


class MarketVerificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='sofia-market-verification-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        captured = '2026-10-29T10:51:02Z'
        rows = [raw_offer(i, observed_at=captured) for i in range(10)]
        capture = dict(version=1, source='imot.bg', mode='daily', started_at='2026-10-29T10:00:00Z',
                       completed_at=captured, complete=True, offers=rows,
                       completion=dict(sources=[dict(key='test', expected_count=10, captured_count=10)], total_unique=10))
        with patch.object(market, 'LocationResolver', EmptyResolver):
            self.manifest, _ = market.build_snapshot(capture, root)
        self.raw_pointer = (root / 'market-active.json').read_bytes()
        self.files = {'/htdocs/private/' + str(path.relative_to(root)).replace('\\', '/'): path.read_bytes()
                      for path in root.rglob('*') if path.is_file()}

    def test_real_prepared_publication_readback_is_fresh(self):
        report = verify_active_market(FilesFTP(self.files), require_fresh=True, expected_pointer=self.raw_pointer, now=NOW)
        self.assertEqual(report['listing_count'], 10)
        self.assertEqual(report['freshness_status'], 'fresh')
        self.assertEqual(report['captured_at'], '2026-10-29T10:51:02Z')
        self.assertEqual(report['snapshot_id'], self.manifest['snapshot_id'])

    def test_later_check_reports_staleness_and_cannot_claim_fresh(self):
        later = NOW + timedelta(days=3)
        report = verify_active_market(FilesFTP(self.files), now=later)
        self.assertEqual(report['freshness_status'], 'stale')
        with self.assertRaises(ValueError): verify_active_market(FilesFTP(self.files), require_fresh=True, now=later)

    def test_corrupted_hosted_summary_is_rejected(self):
        files = dict(self.files)
        key = next(name for name in files if name.endswith('/summary.json'))
        files[key] += b' '
        with self.assertRaises(ValueError): verify_active_market(FilesFTP(files), now=NOW)

    def test_different_active_snapshot_is_not_accepted_as_this_publication(self):
        expected = json.loads(self.raw_pointer)
        expected['snapshot_id'] = 'b' * 32
        expected['manifest_path'] = 'market-snapshots/' + 'b' * 32 + '/manifest.json'
        with self.assertRaises(ValueError):
            verify_active_market(FilesFTP(self.files), expected_pointer=json.dumps(expected).encode(), now=NOW)

    def test_no_snapshot_is_explicitly_unpublished(self):
        self.assertEqual(verify_active_market(FilesFTP({})), dict(available=False, freshness_status='unpublished'))
        with self.assertRaises(ValueError): verify_active_market(FilesFTP({}), require_fresh=True)

    def test_future_capture_time_is_not_fresh(self):
        with self.assertRaises(ValueError): verify_active_market(FilesFTP(self.files), now=NOW - timedelta(days=3))

    def test_reader_commands_need_no_excel_or_geometry_packages(self):
        for name in ['verify_market_snapshot.py', 'deploy_imot_ftps.py']:
            result = subprocess.run([sys.executable, '-S', str(Path(__file__).with_name(name)), '--help'], capture_output=True, text=True)
            with self.subTest(name=name): self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__': unittest.main()
