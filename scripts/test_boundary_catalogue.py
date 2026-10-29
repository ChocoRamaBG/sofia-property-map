"""Official parcel universe, geometry integrity and verified map-point fixtures."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from shapely.geometry import MultiPolygon, Point, Polygon, box, mapping

import build_boundary_snapshot as boundary


STAMP = '2026-10-29T10:00:00Z'


def synthetic_snapshot(path, *, split=False):
    path.mkdir()
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE observations (id TEXT PRIMARY KEY, identity TEXT, feature BLOB, bbox TEXT, vertices INTEGER, unusable INTEGER NOT NULL DEFAULT 0, conflict INTEGER NOT NULL DEFAULT 0, latitude REAL, longitude REAL, source_ordinal INTEGER NOT NULL)')
    geometry = json.loads(json.dumps(mapping(box(23.2, 42.6, 23.21, 42.61))))
    count, bbox = boundary.geometry_vertices(geometry)
    for number in range(1, 1002):
        if split and number == 1000:
            continue
        identifier = f'68134.100.{number}'
        feature = {'type': 'Feature', 'id': identifier, 'bbox': bbox, 'geometry': geometry,
                   'properties': {'cadastral_id': identifier, 'area_m2': 100,
                                  'perimeter_m': 40, 'source_key': 'sofia-district-00',
                                  'vertex_count': count, 'native_crs': 'BGS2005_LCC'}}
        # The final valid polygon intentionally has no publishable point.
        lat, lng = (42.605, 23.205) if number <= 1000 else (None, None)
        connection.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (identifier, 'same-fixture', boundary.json_bytes(feature), json.dumps(bbox), count, 0, 0, lat, lng, 0))
    if split:
        for identifier, polygon in [('68134.100.2000', box(23.2,42.6,23.205,42.61)), ('68134.100.2001', box(23.205,42.6,23.21,42.61))]:
            child_geometry = json.loads(json.dumps(mapping(polygon)))
            child_count, child_bbox = boundary.geometry_vertices(child_geometry)
            child_point = boundary.verified_interior_point(polygon, polygon, None)
            feature = {'type': 'Feature', 'id': identifier, 'bbox': child_bbox, 'geometry': child_geometry,
                       'properties': {'cadastral_id': identifier, 'area_m2': 50,
                                      'perimeter_m': 30, 'source_key': 'sofia-district-00',
                                      'vertex_count': child_count, 'native_crs': 'BGS2005_LCC'}}
            connection.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)',
                               (identifier, 'child-fixture', boundary.json_bytes(feature), json.dumps(child_bbox), child_count, 0, 0, child_point[0], child_point[1], 0))
    connection.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('68134.100.99999', '', None, None, 0, 1, 1, None, None, 1))
    sources = [{'key': f'sofia-district-{position:02}',
                'label_bg': f'гр. София (68134) - район Fixture {position}',
                'source_url': f'https://kais.cadastre.bg/bg/OpenData/Download?path=fixture-{position}.zip',
                'captured_at': STAMP, 'archive_sha256': 'a' * 64,
                'projection_sha256': 'b' * 64,
                'record_count': 1002 + int(split) if position == 0 else 1 if position == 1 else 0}
               for position in range(24)]
    manifest = boundary.finish_snapshot(connection, path, sources, 1003 + int(split), 1, 1,
                                        {'fixture_invalid': 1}, 'c' * 64)
    connection.close()
    boundary.validate_publish_tree(path)
    return manifest


class CatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory(prefix='sofia-catalogue-source-')
        cls.source = Path(cls.fixture.name) / 'snapshot'
        cls.manifest = synthetic_snapshot(cls.source)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='sofia-catalogue-test-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / 'snapshot'
        shutil.copytree(self.source, self.root)
        self.manifest = copy.deepcopy(type(self).manifest)

    def write_manifest(self):
        (self.root / 'manifest.json').write_bytes(boundary.json_bytes(self.manifest))

    def replace_catalogue(self, change):
        path = self.root / 'catalogue.tsv'
        raw = change(path.read_bytes())
        path.write_bytes(raw)
        self.manifest['catalogue'].update(bytes=len(raw), sha256=boundary.digest(raw))
        self.write_manifest()

    def test_current_universe_includes_invalid_and_unlocatable_ids(self):
        rows = list(boundary.catalogue_rows(self.root, self.manifest))
        self.assertEqual((len(rows), self.manifest['mapped_point_count'], self.manifest['unmapped_point_count']), (1002, 1000, 2))
        lookup = {row[0]: row[1:] for row in rows}
        self.assertEqual(lookup['68134.100.99999'], (None, None, 1, 'unavailable'))
        self.assertEqual(lookup['68134.100.1001'], (None, None, 0, 'unavailable'))
        self.assertEqual(boundary.catalogue_ids(self.root, self.manifest), set(lookup))

    def test_legacy_union_keeps_excluded_ids_and_same_full_geometry(self):
        self.manifest['version'] = 1
        for field in ('catalogue', 'catalogue_count', 'mapped_point_count', 'unmapped_point_count', 'point_method'):
            self.manifest.pop(field)
        (self.root / 'catalogue.tsv').unlink()
        self.write_manifest()
        self.assertEqual(boundary.validate_publish_tree(self.root)['version'], 1)
        ids = boundary.catalogue_ids(self.root, self.manifest)
        self.assertEqual(len(ids), 1002)
        self.assertIn('68134.100.99999', ids)
        for info in self.manifest['shards'] + [self.manifest['index'], self.manifest['ambiguous_index']]:
            self.assertEqual((self.root / info['file']).read_bytes(), (self.source / info['file']).read_bytes())

    def test_hash_tampering_rejected_even_by_streaming_reader(self):
        path = self.root / 'catalogue.tsv'
        path.write_bytes(path.read_bytes().replace(b'42.6050000', b'42.6060000', 1))
        with self.assertRaises(ValueError): list(boundary.catalogue_rows(self.root, self.manifest))

    def test_sorted_unique_and_exact_source_bounds(self):
        self.replace_catalogue(lambda raw: raw.replace(b'\t0\tmapped', b'\t24\tmapped', 1))
        with self.assertRaises(ValueError): boundary.validate_publish_tree(self.root)

    def test_current_id_union_rejects_removed_or_fabricated_identifier(self):
        self.replace_catalogue(lambda raw: raw.replace(b'68134.100.99999', b'68134.100.99998'))
        with self.assertRaises(ValueError): boundary.validate_publish_tree(self.root)

    def test_point_outside_polygon_rejected_with_valid_hash_and_bounds(self):
        self.replace_catalogue(lambda raw: raw.replace(b'42.6050000\t23.2050000', b'42.6150000\t23.2050000', 1))
        with self.assertRaises(ValueError): boundary.validate_publish_tree(self.root)

    def test_unavailable_id_cannot_publish_coordinates(self):
        self.replace_catalogue(lambda raw: raw.replace(b'68134.100.99999\t\t\t1\tunavailable', b'68134.100.99999\t42.6050000\t23.2050000\t1\tunavailable'))
        with self.assertRaises(ValueError): boundary.validate_publish_tree(self.root)

    def test_manifest_point_counts_are_enforced(self):
        self.manifest['mapped_point_count'] -= 1
        self.manifest['unmapped_point_count'] += 1
        self.write_manifest()
        with self.assertRaises(ValueError): boundary.validate_publish_tree(self.root)

    def test_split_has_two_new_current_ids_and_no_inferred_successor_links(self):
        new_root = Path(self.folder.name) / 'split-snapshot'
        new_manifest = synthetic_snapshot(new_root, split=True)
        earlier = boundary.catalogue_ids(self.root, self.manifest)
        current = boundary.catalogue_ids(new_root, new_manifest)
        self.assertEqual(earlier - current, {'68134.100.1000'})
        self.assertEqual(current - earlier, {'68134.100.2000', '68134.100.2001'})
        self.assertEqual(current & earlier, earlier - {'68134.100.1000'})
        for info in new_manifest['shards']:
            data = json.loads((new_root / info['file']).read_bytes())
            children = [f for f in data['features'] if f['id'] in current - earlier]
            for feature in children:
                self.assertEqual(set(feature['properties']), {'cadastral_id', 'area_m2', 'perimeter_m', 'source_key', 'vertex_count', 'native_crs'})
        self.assertEqual(new_manifest['mapped_point_count'], self.manifest['mapped_point_count'] + 1)


class VerifiedInteriorPointTests(unittest.TestCase):
    def test_concave_polygon_with_hole_uses_true_interior(self):
        shape = Polygon([(23.2,42.6),(23.23,42.6),(23.23,42.63),(23.22,42.63),
                         (23.22,42.61),(23.21,42.61),(23.21,42.63),(23.2,42.63)],
                        holes=[[(23.201,42.601),(23.201,42.605),(23.205,42.605),(23.205,42.601)]])
        point = boundary.verified_interior_point(shape, shape, None)
        self.assertIsNotNone(point)
        self.assertTrue(shape.contains(Point(point[1], point[0])))
        self.assertEqual(shape.wkb, Polygon(shape.exterior, shape.interiors).wkb)

    def test_disconnected_parts_are_preserved(self):
        shape = MultiPolygon([box(23.2,42.6,23.21,42.61),box(23.4,42.7,23.42,42.72)])
        original = shape.wkb
        point = boundary.verified_interior_point(shape, shape, None)
        self.assertTrue(shape.contains(Point(point[1], point[0])))
        self.assertEqual(shape.wkb, original)

    def test_rounding_onto_edge_has_no_fabricated_fallback(self):
        shape = box(23.20000001,42.60000001,23.20000004,42.60000004)
        self.assertIsNone(boundary.verified_interior_point(shape, shape, None))

    def test_point_must_pass_inverse_native_containment(self):
        class IncorrectInverse:
            def transform(self, x, y, *, direction=None, **kwargs):
                return (x + .5, y + .5) if direction == 'INVERSE' else (x, y)
        shape = box(23.2,42.6,23.21,42.61)
        self.assertIsNone(boundary.verified_interior_point(shape, shape, IncorrectInverse()))


if __name__ == '__main__': unittest.main()
