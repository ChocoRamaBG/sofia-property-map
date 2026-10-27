"""Exercise the actual read-only PHP market reader with synthetic listing data."""
from pathlib import Path
import base64
import copy
import json
import os
import shutil
import subprocess
import unittest

PHP = os.environ.get('SOFIA_PHP_BINARY') or shutil.which('php')
API = Path(__file__).resolve().parents[1] / 'public/market.php'
STAMP = '2026-10-27T12:00:00Z'
FEATURES = dict(construction_type='brick', furnishing='furnished', building_year=2015,
                year_basis='built', floor_number=3, total_floors=6, elevator='yes',
                checked_at=STAMP, source='description')
AGENCY = dict(name='Example Agency', profile_url='https://example.imot.bg/',
              phone='+35921234567', website='https://example.com/',
              checked_at=STAMP, evidence='professional_profile')
ESTIMATE = dict(status='available', method_version=3, peer_count=10,
                median_eur_per_sqm=2500, p25_eur_per_sqm=2300, p75_eur_per_sqm=2700,
                indicated_price_eur=200000, range_low_eur=184000, range_high_eur=216000,
                location_basis='neighborhood', evidence=dict(quality='limited',
                matched_fields=['neighborhood', 'type', 'construction_type'],
                missing_fields=['vat_basis', 'construction_age', 'completion_stage', 'area_basis', 'floor', 'furnishing', 'condition', 'elevator', 'area_tolerance', 'street'], spread_pct=16,
                price_position='within_range', duplicate_peer_count=0,
                unknown_physical_duplicates=True))
OFFER = dict(id='abcdef1234', url='https://www.imot.bg/obiava-abcdef1234-test',
             vat_basis='included', historical=False, comparison={}, change={},
             price_eur=200000, area_sqm=80, eur_per_sqm=2500,
             seller_type='agency', seller_evidence='agency_profile', seller_checked_at=STAMP,
             property_features=FEATURES, agency=AGENCY, asking_estimate=ESTIMATE)


def execute(offer, filters=None):
    payload = base64.b64encode(json.dumps({'offer': offer, 'filters': filters or {}}).encode()).decode()
    runner = r'''
    $source = file_get_contents($argv[1]);
    $end = strpos($source, "\ntry {");
    if ($end === false) throw new Exception('Missing reader entry boundary');
    eval(substr($source, 5, $end - 5));
    $data = json_decode(base64_decode($argv[2]), true, 32, JSON_THROW_ON_ERROR);
    try {
        $row = market_offer($data['offer']);
        $_GET = $data['filters'];
        $filters = market_listing_filters(['filter_options' => []]);
        echo json_encode(['accepted' => true, 'matches' => market_matches($row, $filters)], JSON_THROW_ON_ERROR);
    } catch (Throwable $error) { echo json_encode(['accepted' => false, 'error' => $error->getMessage()]); }
    '''
    result = subprocess.run([PHP, '-r', runner, str(API), payload], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@unittest.skipUnless(PHP, 'PHP executable required')
class MarketFeatureReaderTests(unittest.TestCase):
    def test_real_producer_rows_match_php_contract(self):
        from test_imot_market import ModelTests, raw_offer
        fixture = ModelTests()
        try:
            rows, _, _, _ = fixture.build([raw_offer(i) for i in range(10)])
            for row in rows:
                self.assertTrue(execute(row)['accepted'])
        finally:
            fixture.doCleanups()

    def test_new_schema_and_all_matching_filters(self):
        self.assertEqual(execute(OFFER, dict(construction_type='brick', furnishing='furnished', elevator='yes')), dict(accepted=True, matches=True))

    def test_mismatching_feature_filters_apply_to_entire_result(self):
        for key, value in [('construction_type', 'panel'), ('furnishing', 'unfurnished'), ('elevator', 'no')]:
            with self.subTest(key=key):
                self.assertEqual(execute(OFFER, {key: value}), dict(accepted=True, matches=False))

    def test_legacy_v2_stays_readable_and_unknown_filter_matches(self):
        row = copy.deepcopy(OFFER)
        row.pop('agency'); row.pop('property_features')
        row['asking_estimate'].pop('evidence'); row['asking_estimate']['method_version'] = 2
        self.assertEqual(execute(row, {'furnishing': 'unknown'}), dict(accepted=True, matches=True))
        self.assertFalse(execute(row, {'construction_type': 'brick'})['matches'])

    def test_private_seller_cannot_publish_agency_contacts(self):
        row = copy.deepcopy(OFFER)
        row.update(seller_type='private', seller_evidence='explicit_private_claim')
        self.assertFalse(execute(row)['accepted'])

    def test_reject_untrusted_contact_urls_and_extra_data(self):
        for field, value in [('profile_url', 'https://example.imot.bg.attacker.com/'), ('profile_url', 'https://www.imot.bg/'), ('website', 'javascript:alert(1)'), ('website', 'https://user:password@example.com/'), ('phone', 'call me')]:
            row = copy.deepcopy(OFFER); row['agency'][field] = value
            with self.subTest(field=field, value=value): self.assertFalse(execute(row)['accepted'])
        row = copy.deepcopy(OFFER); row['agency']['private_person'] = 'forbidden'
        self.assertFalse(execute(row)['accepted'])

    def test_reject_conflicting_or_invalid_features(self):
        for fields in [dict(building_year=None), dict(total_floors=2), dict(furnishing='yes'), dict(floor_number=True), dict(elevator='yes', secret='forbidden')]:
            row = copy.deepcopy(OFFER); row['property_features'].update(fields)
            with self.subTest(fields=fields): self.assertFalse(execute(row)['accepted'])

    def test_reject_unsupported_estimate_evidence(self):
        for fields in [dict(quality='certain'), dict(matched_fields=['neighborhood'], missing_fields=['neighborhood']), dict(unknown_physical_duplicates=False), dict(price_position='guaranteed_bargain')]:
            row = copy.deepcopy(OFFER); row['asking_estimate']['evidence'].update(fields)
            with self.subTest(fields=fields): self.assertFalse(execute(row)['accepted'])

    def test_reject_unknown_filter(self):
        self.assertFalse(execute(OFFER, {'furnishing': 'luxury'})['accepted'])


if __name__ == '__main__': unittest.main()
