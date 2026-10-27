"""Offline municipal reference fixtures. No real company/address rows."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import municipal_business_addresses as municipal


def zipped(name, payload):
    output = io.BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr(name, payload)
    return output.getvalue()


def feature(identifier, street='ул. Тестова', number='1', quarter='ж.к. Пример', block='10', entrance='а', region='район Примерен', lng=23.3, lat=42.7, settlement='гр. София'):
    return {'type': 'Feature', 'properties': {'rn': identifier, 'region': region, 'settlement': settlement, 'lareaunit': quarter,
                                             'block': block, 'street': street, 'streetnum': number, 'entrance': entrance},
            'geometry': {'type': 'Point', 'coordinates': [lng, lat]}}


def reference(features=None, aliases=None, crs=None):
    data = {'type': 'FeatureCollection', 'features': features or [feature('r1')]}
    if crs:
        data['crs'] = {'type': 'name', 'properties': {'name': crs}}
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=['rn', 'new_name', 'name', 'resolution_renaming'])
    writer.writeheader()
    for row in aliases or [{'rn': 'a1', 'new_name': 'ул. Тестова', 'name': 'ул. Стара', 'resolution_renaming': 'Решение 1/2020'}]:
        writer.writerow(row)
    return municipal.load_reference(zipped('address_sofia.geojson', json.dumps(data, ensure_ascii=False).encode()),
                                    zipped('streets_names_new_old.csv', stream.getvalue().encode()))


class MunicipalReferenceTests(unittest.TestCase):
    def test_street_number_retains_all_exact_points(self):
        ref = reference([feature('r1'), feature('r2', entrance='б', lng=23.301)])
        result = municipal.resolve_company_address('ул. „ТЕСТОВА“ № 1, ет. 2, телефон: 000000000', ref)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['reference_ids'], ['r1', 'r2'])
        self.assertEqual(len(result[0]['points']), 2)
        self.assertNotIn('телефон', result[0]['address_label'])
        self.assertEqual(result[0]['method'], 'municipal_street_number')

    def test_exact_number_suffix_and_no_number_marker(self):
        ref = reference([feature('r1', number='1а')])
        self.assertTrue(municipal.resolve_company_address('ул. Тестова 1 А', ref))
        self.assertFalse(municipal.resolve_company_address('ул. Тестова № 1', ref))

    def test_quarter_and_entrance_restrict_records(self):
        ref = reference([feature('r1'), feature('r2', entrance='б'), feature('r3', quarter='ж.к. Друг')])
        result = municipal.resolve_company_address('ж.к. Пример, ул. Тестова № 1, вх. А', ref)
        self.assertEqual(result[0]['reference_ids'], ['r1'])

    def test_quarter_block_without_street_is_supported(self):
        ref = reference([feature('r1', street='', number='')])
        result = municipal.resolve_company_address('ж.к. Пример, бл. 10, вх. А, ап. 4', ref)
        self.assertEqual(result[0]['method'], 'municipal_quarter_block')
        self.assertEqual(result[0]['reference_ids'], ['r1'])
        self.assertFalse(municipal.resolve_company_address('бл. 10, вх. А', ref))

    def test_region_does_not_guess_when_conflicting(self):
        ref = reference([feature('r1'), feature('r2', region='район Друг')])
        result = municipal.resolve_company_address('район Примерен, ул. Тестова № 1', ref)
        self.assertEqual(result[0]['reference_ids'], ['r1'])

    def test_ambiguous_historical_name_preserves_all_targets(self):
        aliases = [{'rn': 'a1', 'new_name': 'ул. Тестова', 'name': 'ул. Стара', 'resolution_renaming': 'Решение 1'},
                   {'rn': 'a2', 'new_name': 'бул. Друга', 'name': 'ул. Стара', 'resolution_renaming': 'Решение 2'}]
        ref = reference([feature('r1'), feature('r2', street='бул. Друга')], aliases)
        result = municipal.resolve_company_address('ул. Стара № 1', ref)
        self.assertEqual(len(result), 2)
        self.assertEqual({x['reference_ids'][0] for x in result}, {'r1', 'r2'})
        self.assertTrue(all(x['method'] == 'municipal_historical_street_number' for x in result))

    def test_untyped_alias_does_not_invent_street_kind(self):
        aliases = [{'rn': 'a1', 'new_name': 'Тестова', 'name': 'Стара', 'resolution_renaming': ''}]
        ref = reference([feature('r1'), feature('r2', street='бул. Тестова')], aliases)
        result = municipal.resolve_company_address('ул. Стара № 1', ref)
        self.assertEqual(len(result), 2)

    def test_similar_names_and_number_ranges_are_unresolved(self):
        ref = reference()
        for raw in ['ул. Тестоваа № 1', 'ул. Тестова № 1-3', 'ул. Тестова № 1/2', 'ул. Тестова № 1 и 2', 'ул. Тестова № 1, ул. Друга № 2']:
            with self.subTest(raw=raw):
                self.assertFalse(municipal.resolve_company_address(raw, ref))

    def test_more_than_32_ids_rejected_without_truncation(self):
        ref = reference([feature('r' + str(i)) for i in range(33)])
        self.assertFalse(municipal.resolve_company_address('ул. Тестова № 1', ref))

    def test_other_settlements_are_not_sofia_city(self):
        ref = reference([feature('r1', settlement='Друг град')])
        self.assertEqual(ref.records, [])

    def test_invalid_geometry_or_explicit_crs_is_rejected(self):
        for kwargs in [{'features': [feature('r1', lat=0)]}, {'features': [feature('r1', lng=100)]}, {'crs': 'EPSG:3857'}, {'crs': 'EPSG:4326'}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                reference(**kwargs)
        ref = reference(crs='OGC:CRS84')
        self.assertTrue(ref.provenance['publisher_crs_explicit'])

    def test_duplicate_reference_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            reference([feature('r1'), feature('r1', lng=23.31)])

    def test_archive_traversal_extra_members_and_wrong_schema_are_rejected(self):
        for name in ['../address_sofia.geojson', 'unknown.geojson']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                municipal.zip_member(zipped(name, b'{}'), 'address_sofia.geojson', 100)
        with self.assertRaises(ValueError):
            municipal.zip_member(zipped('address_sofia.geojson', b'x' * 101), 'address_sofia.geojson', 100)

    def test_ckan_identity_license_resource_and_url_are_validated(self):
        spec = municipal.SOURCES['addresses']
        url = 'https://urbandata.sofia.bg/dataset/' + 'a' * 36 + '/resource/' + spec['resource_id'] + '/download/address_sofia.zip'
        data = {'success': True, 'result': {'name': spec['dataset'], 'license_id': 'cc-by', 'extras': [{'key': 'Актуален към', 'value': '28.08.2026 г.'}],
                                           'resources': [{'id': spec['resource_id'], 'format': 'GeoJSON', 'url': url}]}}
        resource, as_of = municipal.package_resource(json.dumps(data).encode(), 'addresses')
        self.assertEqual(as_of, '2026-08-28')
        self.assertEqual(resource['url'], url)
        data['result']['resources'][0]['url'] = 'https://example.invalid/data.zip'
        with self.assertRaises(ValueError):
            municipal.package_resource(json.dumps(data).encode(), 'addresses')

    def test_source_revision_and_labels_are_safe(self):
        result = municipal.resolve_company_address('ул. Стара № 1, email: confidential@example.invalid', reference())
        self.assertTrue(result)
        self.assertRegex(result[0]['source_revision'], r'^[0-9a-f]{64}$')
        self.assertLessEqual(len(result[0]['address_label']), 240)
        self.assertNotIn('@', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
