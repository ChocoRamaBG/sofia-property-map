"""Real PHP dispatch against immutable synthetic catalogues and a fake read-only PDO.

The fixture substitutes only the connection constructor; production routing,
filtering, geometry hydration and JSON responses execute unchanged.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PHP = os.environ.get('SOFIA_PHP_BINARY') or shutil.which('php')
STAMP = '2026-10-29T10:00:00Z'
OLD = '68134.100.900000'
UNMAPPED = '68134.100.800000'


def encoded(value): return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
def descriptor(name, raw, key, count): return dict(file=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), **{key: count})


def fixture_snapshot(private, count=3):
    snapshot_id = 'a' * 32
    folder = private / 'boundary-snapshots' / snapshot_id
    folder.mkdir(parents=True)
    features = []
    catalogue = []
    index = []
    for number in range(1, count + 1):
        identifier = f'68134.100.{number}'
        lat = 42.6 + ((number - 1) // 60) * .0015
        lng = 23.2 + ((number - 1) % 60) * .0015
        bbox = [round(lng - .0002, 7), round(lat - .0002, 7), round(lng + .0002, 7), round(lat + .0002, 7)]
        ring = [[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]], [bbox[0], bbox[1]]]
        features.append(dict(type='Feature', id=identifier, bbox=bbox,
            geometry=dict(type='Polygon', coordinates=[ring]), properties=dict(cadastral_id=identifier,
                area_m2=100, perimeter_m=40, source_key='sofia-district-00', vertex_count=5, native_crs='BGS2005_LCC')))
        catalogue.append(f'{identifier}\t{lat:.7f}\t{lng:.7f}\t0\tmapped\n')
    catalogue.append(f'{UNMAPPED}\t\t\t1\tunavailable\n')
    features.sort(key=lambda row: row['id'])
    shards = []
    for start in range(0, len(features), 250):
        rows = features[start:start + 250]
        number = len(shards)
        name = f'boundaries-{number:04}.json'
        raw = encoded(dict(type='FeatureCollection', features=rows))
        (folder / name).write_bytes(raw)
        bounds = [min(row['bbox'][0] for row in rows), min(row['bbox'][1] for row in rows), max(row['bbox'][2] for row in rows), max(row['bbox'][3] for row in rows)]
        shards.append(descriptor(name, raw, 'feature_count', len(rows)) | dict(bounds=bounds, vertex_count=len(rows) * 5))
        for row in rows:
            bbox = row['bbox']
            index.append(row['id'] + '\t' + '\t'.join(f'{x:.6f}' for x in [bbox[1], bbox[3], bbox[0], bbox[2]]) + f'\t{number}\n')
    catalogue_raw = ''.join(sorted(catalogue)).encode()
    index_raw = ''.join(index).encode()
    excluded_raw = (UNMAPPED + '\n').encode()
    for name, raw in [('catalogue.tsv', catalogue_raw), ('boundaries.tsv', index_raw), ('ambiguous.tsv', excluded_raw)]: (folder / name).write_bytes(raw)
    sources = [dict(key=f'sofia-district-{i:02}', label_bg=f'гр. София (68134) - район Fixture {i}',
                    source_url=f'https://kais.cadastre.bg/bg/OpenData/Download?path=fixture-{i}.zip',
                    captured_at=STAMP, archive_sha256='b' * 64, projection_sha256='c' * 64,
                    record_count=count if i == 0 else 1 if i == 1 else 0) for i in range(24)]
    manifest = dict(version=2, reference_format='boundary-bbox-geojson-v1', snapshot_id=snapshot_id,
                    generated_at=STAMP, captured_at=STAMP, crs='EPSG:4326', native_crs='EPSG:7801',
                    coordinate_precision=7, index_precision=6, completion=dict(status='complete', source_count=24, record_count=count + 1),
                    min_zoom=16, source_url='https://kais.cadastre.bg/bg/OpenData', parcel_count=count, feature_count=count,
                    record_count=count + 1, ambiguous_parcel_count=1, geometry_method='fixture_no_repair', transform_accuracy_m=1,
                    index=descriptor('boundaries.tsv', index_raw, 'rows', count), ambiguous_index=descriptor('ambiguous.tsv', excluded_raw, 'rows', 1),
                    catalogue=descriptor('catalogue.tsv', catalogue_raw, 'rows', count + 1), catalogue_count=count + 1,
                    mapped_point_count=count, unmapped_point_count=1, point_method='strict_native_and_published_interior_v1',
                    sources=sources, shards=shards, vertex_count=count * 5)
    save_manifest(private, manifest)
    return manifest


def save_manifest(private, manifest):
    (private / 'boundaries-active.json').write_bytes(encoded(manifest))
    (private / 'boundary-snapshots' / manifest['snapshot_id'] / 'manifest.json').write_bytes(encoded(manifest))


PDO_FIXTURE = r'''<?php
class FixtureStatement extends PDOStatement {
    private array $rows = []; private int $offset = 0;
    public function __construct(private string $sql, array $rows = []) { $this->rows = $rows; }
    public function execute(?array $params = null): bool {
        $this->offset = 0;
        if (str_contains($this->sql, 'FROM parcels')) {
            $id = $params['id'] ?? '';
            $this->rows = in_array($id, ['68134.100.1', '68134.100.900000', '12345.100.1'], true)
                ? [['cadastral_id' => $id, 'lat' => 42.75, 'lng' => 23.45, 'document_count' => $id === '68134.100.900000' ? 1 : 0,
                    'has_building_permit' => 0, 'has_projecting_visa' => $id === '68134.100.900000' ? 1 : 0, 'has_exploitation_certificate' => 0]] : [];
        } elseif (str_contains($this->sql, 'OCTET_LENGTH(raw_fields)')) {
            $raw = '{"Investor":"Investor One","Address":"Test street"}';
            $this->rows = [['source_code' => 'building_permits', 'document_hash' => str_repeat('d', 64), 'record_key' => 'P-1', 'raw_bytes' => strlen($raw), 'raw_fields' => $raw]];
        } elseif (str_contains($this->sql, 'SELECT parcel_cadastral_id FROM parcel_documents')) $this->rows = [['parcel_cadastral_id' => '68134.100.2']];
        elseif (str_contains($this->sql, 'JOIN source_documents')) {
            $this->rows = ($params['id'] ?? '') === '68134.100.900000' ? [['code' => 'projecting_visas', 'label_bg' => 'Визи', 'label_en' => 'Visas', 'source_url' => 'https://www.sofia.bg/', 'snapshot_date' => null, 'source_snapshot' => null,
                'document_hash' => str_repeat('e', 64), 'record_key' => 'V-OLD', 'raw_fields' => '{"History":"Retained document"}', 'document_snapshot' => null]] : [];
        }
        return true;
    }
    public function fetch(int $mode = PDO::FETCH_DEFAULT, int $cursorOrientation = PDO::FETCH_ORI_NEXT, int $cursorOffset = 0): mixed { return $this->rows[$this->offset++] ?? false; }
    public function fetchAll(int $mode = PDO::FETCH_DEFAULT, mixed ...$args): array { return array_slice($this->rows, $this->offset); }
    public function fetchColumn(int $column = 0): mixed { $row = $this->fetch(); return $row === false ? false : (array_values($row)[$column] ?? false); }
}
class FixturePDO extends PDO {
    public function __construct() {}
    public function quote(string $string, int $type = PDO::PARAM_STR): string|false { return "'" . str_replace("'", "''", $string) . "'"; }
    public function prepare(string $query, array $options = []): PDOStatement|false { return new FixtureStatement($query); }
    public function query(string $query, ?int $fetchMode = null, mixed ...$fetchModeArgs): PDOStatement|false {
        $rows = [];
        if (str_contains($query, 'GROUP BY parcel_cadastral_id') && str_contains($query, 'MAX(')) $rows = [
            ['cadastral_id' => '68134.100.2', 'document_count' => 1, 'has_building_permit' => 1, 'has_projecting_visa' => 0, 'has_exploitation_certificate' => 1],
            ['cadastral_id' => '68134.100.900000', 'document_count' => 1, 'has_building_permit' => 0, 'has_projecting_visa' => 1, 'has_exploitation_certificate' => 0]];
        elseif (str_contains($query, 'GROUP BY parcel_cadastral_id, source_code')) $rows = [
            ['parcel_cadastral_id' => '68134.100.2', 'source_code' => 'building_permits'], ['parcel_cadastral_id' => '68134.100.900000', 'source_code' => 'projecting_visas']];
        elseif (str_contains($query, 'SELECT ds.code,')) $rows = [['code' => 'building_permits', 'document_count' => 1], ['code' => 'projecting_visas', 'document_count' => 1]];
        elseif (str_contains($query, 'SELECT pd.source_code,')) $rows = [['source_code' => 'building_permits', 'plot_count' => 0], ['source_code' => 'projecting_visas', 'plot_count' => 1]];
        elseif (str_contains($query, 'COUNT(')) $rows = [[0]];
        return new FixtureStatement($query, $rows);
    }
}
'''


@unittest.skipUnless(PHP, 'PHP executable required')
class ParcelCatalogueApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sofia-parcel-api-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.private = self.root / 'private'; self.private.mkdir()
        self.manifest = fixture_snapshot(self.private)
        self.folder = self.private / 'boundary-snapshots' / self.manifest['snapshot_id']
        source = (ROOT / 'public/api.php').read_text(encoding='utf-8')
        source, replaced = re.subn(r'\$pdo = new PDO\(\$dsn,.*?\n    \]\);', '$pdo = new FixturePDO();', source, count=1, flags=re.S)
        self.assertEqual(replaced, 1, 'Only the external connection constructor is substituted')
        (self.root / 'api.php').write_text(source, encoding='utf-8')
        for name in ['boundary-data.php', 'parcel-catalogue.php']: shutil.copyfile(ROOT / 'public' / name, self.root / name)
        (self.root / 'fixture.php').write_text(PDO_FIXTURE, encoding='utf-8')
        (self.private / 'config.php').write_text("<?php return ['host'=>'fixture','database'=>'fixture','port'=>3306,'username'=>'fixture','password'=>'fixture'];", encoding='utf-8')

    def request(self, **params):
        runner = "require $argv[1].'/fixture.php'; $_GET=json_decode($argv[2],true,32,JSON_THROW_ON_ERROR); include $argv[1].'/api.php';"
        result = subprocess.run([PHP, '-r', runner, str(self.root), json.dumps(params)], capture_output=True, text=True, check=True)
        self.last_stderr = result.stderr
        try: return json.loads(result.stdout)
        except json.JSONDecodeError: self.fail(result.stdout + result.stderr)

    def viewport(self, **params): return self.request(action='viewport', north=43, south=42, east=24, west=23, zoom=17, **params)

    def rich_filter_ids(self, params):
        p0, p1 = 'purpose-' + '0' * 16, 'purpose-' + '1' * 16
        u0, u1 = 'use-' + '0' * 16, 'use-' + '1' * 16
        lines = '\n'.join([f'68134.100.1\t100\t0\t0\t0\t0\t0', f'68134.100.2\t200\t0\t0\t1\t0\t0', f'68134.100.3\t300\t0\t0\t1\t1\t0']) + '\n'
        index = self.root / 'attributes.tsv'; index.write_bytes(lines.encode('ascii'))
        cadastre = dict(version=2, index_path=str(index), index=descriptor('attributes.tsv', lines.encode(), 'rows', 3),
            sources=[dict(usable_parcel_count=3 if i == 0 else 0) for i in range(24)], records=[dict(records=3)],
            ambiguous_lookup={}, parcel_count=3, area_min_m2=100, area_max_m2=300,
            facets=dict(districts=[dict(count=3 if i == 0 else 0) for i in range(24)], purposes=[dict(count=1), dict(count=2)], uses=[dict(count=2), dict(count=1)], property_types=[dict(count=3)]),
            facet_lookup=dict(districts={'sofia-district-00': 0}, purposes={p0: 0, p1: 1}, uses={u0: 0, u1: 1}, property_types={'property-' + '0' * 16: 0}))
        registry = dict(format=1, flags={}, documents=[], by_id={'68134.100.2': [], '68134.100.3': []},
            qualified_ids={'68134.100.3': True}, certificate_ids={},
            source_ids=dict(building_permits={'68134.100.2': True, '68134.100.3': True}, projecting_visas={'68134.100.3': True}))
        runner = r'''
        require $argv[1].'/fixture.php';
        $source=file_get_contents($argv[1].'/api.php'); $source=substr($source,0,strpos($source,"\ntry {"));
        $source=str_replace('__DIR__',var_export($argv[1],true),$source); eval(substr($source,5));
        require $argv[1].'/boundary-data.php';
        $context=json_decode($argv[2],true,32,JSON_THROW_ON_ERROR); $_GET=$context['params'];
        $snapshot=load_boundary_snapshot(); $ids=parcel_catalogue_candidates($snapshot);
        echo json_encode(array_keys(parcel_catalogue_filter_ids(new FixturePDO(),$context['registry'],$context['cadastre'],map_filter_params(),$ids)));
        '''
        result = subprocess.run([PHP, '-r', runner, str(self.root), json.dumps(dict(params=params, registry=registry, cadastre=cadastre))], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_new_ids_and_relocated_markers_do_not_depend_on_mysql(self):
        result = self.viewport()
        self.assertEqual(result['total'], 3)
        rows = {row['cadastral_id']: row for row in result['items']}
        self.assertIn('68134.100.2', rows)
        self.assertEqual(rows['68134.100.1']['lat'], 42.6)
        self.assertEqual(rows['68134.100.2']['catalogue_status'], 'current')
        self.assertEqual(rows['68134.100.2']['coordinate_method'], 'official_geometry_interior')
        self.assertNotIn(OLD, rows)

    def test_meta_counts_current_official_points_not_legacy_mysql(self):
        result = self.request(action='meta')
        self.assertEqual(result['counts']['plots'], 3)
        self.assertEqual(result['counts']['plots_by_source']['building_permits'], 1)
        self.assertEqual(result['counts']['plots_by_source']['projecting_visas'], 0)
        self.assertEqual(result['parcel_catalogue']['catalogue_count'], 4)
        self.assertTrue(result['parcel_catalogue']['available'])

    def test_new_exact_identifier_search_and_plot_are_available(self):
        result = self.request(action='search', q='68134.100.2')
        self.assertEqual((result['total'], result['mapped_total']), (1, 1))
        self.assertEqual(result['items'][0]['catalogue_status'], 'current')
        plot = self.request(action='plot', id='68134.100.2')
        self.assertEqual(plot['plot']['catalogue_status'], 'current')
        self.assertTrue(plot['plot']['has_building_permit'])

    def test_unmapped_current_identifier_is_not_mislabelled_retired(self):
        result = self.request(action='plot', id=UNMAPPED)
        self.assertEqual(result['plot']['catalogue_status'], 'current')
        self.assertIsNone(result['plot']['lat'])
        self.assertEqual(result['plot']['coordinate_method'], 'unavailable')

    def test_other_settlement_history_is_outside_sofia_catalogue_scope(self):
        result = self.request(action='plot', id='12345.100.1')
        self.assertEqual(result['plot']['catalogue_status'], 'unavailable')
        self.assertEqual(result['plot']['catalogue_source']['scope'], 'sofia_68134_land_parcels')

    def test_historical_identifier_keeps_documents_but_not_current_map(self):
        result = self.request(action='search', q=OLD)
        self.assertEqual((result['total'], result['mapped_total']), (1, 0))
        self.assertEqual(result['items'][0]['catalogue_status'], 'not_in_latest_snapshot')
        plot = self.request(action='plot', id=OLD)
        self.assertEqual(plot['plot']['catalogue_status'], 'not_in_latest_snapshot')
        self.assertEqual(plot['sources'][0]['documents'][0]['record_key'], 'V-OLD')

    def test_split_parent_history_does_not_inherit_documents_to_new_children(self):
        # The fixture represents two newly published IDs and an old parent that
        # disappeared from the export. No successor relation is inferred.
        children = ['68134.100.2', '68134.100.3']
        view = self.viewport()
        self.assertTrue(set(children) <= {row['cadastral_id'] for row in view['items']})
        self.assertNotIn(OLD, {row['cadastral_id'] for row in view['items']})
        for child in children:
            result = self.request(action='plot', id=child)
            self.assertEqual(result['plot']['catalogue_status'], 'current')
            self.assertFalse(result['plot']['has_projecting_visa'])
            self.assertEqual(result['sources'], [])
            self.assertNotIn('predecessor', result)
            exact = self.request(action='search', q=child)
            self.assertEqual(exact['mapped_total'], 1)
        boundary = self.request(action='boundaries', north=42.61, south=42.59, east=23.21, west=23.19, zoom=17,
                                search_terms=json.dumps(children), search_match='any')
        self.assertEqual({row['id'] for row in boundary['features']}, set(children))
        parent = self.request(action='plot', id=OLD)
        self.assertEqual(parent['plot']['catalogue_status'], 'not_in_latest_snapshot')
        self.assertEqual(parent['sources'][0]['documents'][0]['record_key'], 'V-OLD')

    def test_document_filters_and_database_flags_are_preserved_without_registry_snapshot(self):
        self.assertEqual(self.viewport(record_types='building_permits')['total'], 1)
        self.assertEqual(self.viewport(record_types='building_permits,exploitation_certificates', match='all')['total'], 1)
        self.assertEqual(self.viewport(record_types='projecting_visas')['total'], 0)
        self.assertEqual(self.viewport(record_types='no_records')['total'], 2)

    def test_phrase_search_constrains_new_ids_and_all_map_points(self):
        result = self.viewport(search_terms=json.dumps(['Investor One']))
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['cadastral_id'], '68134.100.2')
        result = self.request(action='search', search_terms=json.dumps(['Investor One', '68134.100.2']), search_match='all')
        self.assertEqual(result['total'], 1)

    def test_area_and_cadastral_facets_combine_on_new_identifiers(self):
        result = self.rich_filter_ids(dict(area_min_m2='150', area_max_m2='250', cadastre_purposes=','.join(['purpose-' + '0' * 16, 'purpose-' + '1' * 16]), cadastre_uses='use-' + '0' * 16))
        self.assertEqual(result, ['68134.100.2'])

    def test_independent_document_periods_and_all_types_keep_new_identifier(self):
        result = self.rich_filter_ids(dict(record_types='building_permits,projecting_visas', match='all', permits_date_from='2026-01-01', visas_date_to='2026-12-31', area_min_m2='250'))
        self.assertEqual(result, ['68134.100.3'])

    def test_no_records_and_area_filters_do_not_restore_historical_parent(self):
        self.assertEqual(self.rich_filter_ids(dict(record_types='no_records', area_max_m2='150')), ['68134.100.1'])

    def test_search_preview_does_not_limit_matching_totals_or_bounds(self):
        shutil.rmtree(self.private / 'boundary-snapshots')
        self.manifest = fixture_snapshot(self.private, 65)
        result = self.request(action='search', q='68134.100')
        self.assertEqual((result['total'], result['mapped_total'], len(result['items'])), (66, 65, 40))
        self.assertTrue(result['truncated'])
        self.assertGreater(result['bounds']['east'], 23.28)
        self.assertNotIn(OLD, {row['cadastral_id'] for row in result['items']})

    def test_complete_adaptive_clusters_preserve_counts(self):
        shutil.rmtree(self.private / 'boundary-snapshots')
        self.manifest = fixture_snapshot(self.private, 3000)
        result = self.viewport()
        self.assertEqual(result['total'], 3000)
        self.assertEqual(sum(row.get('count', 1) for row in result['items']), 3000)
        self.assertLessEqual(len(result['items']), 1800)
        self.assertFalse(result['truncated'])
        self.assertLess(result['cluster_zoom'], 17)
        self.assertEqual(sum(row['certificate_count'] for row in result['items']), 1)

    def test_new_boundary_is_not_filtered_out_by_missing_mysql_row(self):
        result = self.request(action='boundaries', north=42.61, south=42.59, east=23.21, west=23.19, zoom=17, search_terms=json.dumps(['68134.100.2']))
        self.assertEqual(result.get('status'), 'available', str(result) + self.last_stderr)
        self.assertEqual([row['id'] for row in result['features']], ['68134.100.2'])
        self.assertEqual(result['features'][0]['properties']['catalogue_status'], 'current')
        self.assertEqual(result['features'][0]['geometry']['coordinates'][0][0], [23.2013, 42.5998])

    def test_corrupt_catalogue_fails_closed_instead_of_showing_old_mysql(self):
        path = self.folder / 'catalogue.tsv'
        path.write_bytes(path.read_bytes().replace(b'42.6000000', b'42.7000000', 1))
        self.assertIn('error', self.viewport())
        self.assertIn('error', self.request(action='plot', id='68134.100.2'))

    def test_inconsistent_v2_manifest_is_not_silently_downgraded(self):
        self.manifest['mapped_point_count'] += 1
        save_manifest(self.private, self.manifest)
        self.assertIn('error', self.viewport())

    def test_legacy_v1_stays_readable_without_claiming_current_catalogue(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['version'] = 1
        for field in ['catalogue', 'catalogue_count', 'mapped_point_count', 'unmapped_point_count', 'point_method']: manifest.pop(field)
        save_manifest(self.private, manifest)
        plot = self.request(action='plot', id='68134.100.1')
        self.assertEqual(plot['plot']['lat'], 42.75)
        self.assertNotIn('catalogue_status', plot['plot'])
        self.assertFalse(self.request(action='meta')['parcel_catalogue']['available'])


if __name__ == '__main__': unittest.main()
