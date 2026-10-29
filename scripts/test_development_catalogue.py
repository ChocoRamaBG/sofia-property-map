"""Construction-feed locations use the same official parcel universe as the map."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_parcel_catalogue_api import fixture_snapshot, PDO_FIXTURE, OLD, UNMAPPED, save_manifest

ROOT = Path(__file__).resolve().parents[1]
PHP = os.environ.get('SOFIA_PHP_BINARY') or shutil.which('php')
STAMP = '2026-10-29T10:00:00Z'

DEVELOPMENT_PDO = r'''
class DevelopmentFixturePDO extends FixturePDO {
    public function query(string $query, ?int $fetchMode = null, mixed ...$fetchModeArgs): PDOStatement|false {
        if (!str_contains($query, 'FROM parcels')) return parent::query($query, $fetchMode, ...$fetchModeArgs);
        preg_match_all("/'([0-9.]+)'/", $query, $matches);
        $rows = in_array('68134.100.900000', $matches[1], true) ? [['cadastral_id'=>'68134.100.900000','lat'=>42.75,'lng'=>23.45]] : [];
        if (str_contains($query, 'COUNT(*) AS total')) $rows = [['total'=>count($rows),'south'=>$rows ? 42.75 : null,'north'=>$rows ? 42.75 : null,'west'=>$rows ? 23.45 : null,'east'=>$rows ? 23.45 : null]];
        return new FixtureStatement($query, $rows);
    }
}
'''


def registry_fixture():
    documents = []
    for number, (identifier, issued) in enumerate([('68134.100.2', '2026-10-29'), ('68134.100.3', '2026-10-28'), (OLD, '2026-10-27')], 1):
        documents.append(dict(source_code='building_permits', document_hash=f'{number:064x}',
            record_key=f'P-{number}', issued_at=issued, cadastral_ids=[identifier],
            snapshot_date='2026-10-29', snapshot_file=None,
            raw_fields={'Permit number': f'P-{number}', 'Обект': 'Нова жилищна сграда', 'Район': 'Test district'}))
    codes = ['building_permits', 'projecting_visas', 'exploitation_certificates', 'exploitation_certificates_legacy']
    return dict(format=1, generated_at=STAMP, documents=documents,
        sources={code: dict(label_bg=code, source_url='https://www.sofia.bg/', snapshot_date='2026-10-29', snapshot_file=None) for code in codes},
        source_plot_counts={code: 3 if code == 'building_permits' else 0 for code in codes})


@unittest.skipUnless(PHP, 'PHP executable required')
class DevelopmentCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sofia-development-catalogue-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / 'private'; self.private.mkdir()
        self.manifest = fixture_snapshot(self.private)
        self.folder = self.private / 'boundary-snapshots' / self.manifest['snapshot_id']
        for name in ['api.php', 'development-data.php', 'boundary-data.php', 'parcel-catalogue.php']:
            shutil.copyfile(ROOT / 'public' / name, self.root / name)
        (self.root / 'fixture.php').write_text(PDO_FIXTURE + DEVELOPMENT_PDO, encoding='utf-8')
        self.registry = registry_fixture()

    def response(self, params=None, registry=None):
        runner = r'''
        require $argv[1].'/fixture.php';
        $source=file_get_contents($argv[1].'/api.php');
        $source=substr($source,0,strpos($source,"\ntry {"));
        $source=str_replace('__DIR__',var_export($argv[1],true),$source);
        eval(substr($source,5));
        require $argv[1].'/development-data.php';
        $context=json_decode($argv[2],true,32,JSON_THROW_ON_ERROR); $_GET=$context['params'];
        try { echo json_encode(development_response(new DevelopmentFixturePDO(),$context['registry'],development_params()), JSON_THROW_ON_ERROR); }
        catch (Throwable $error) { echo json_encode(['error'=>$error->getMessage()]); }
        '''
        result = subprocess.run([PHP, '-r', runner, str(self.root), json.dumps(dict(params=params or {}, registry=registry or self.registry))], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_feed_uses_new_children_without_sql_and_preserves_parent_document(self):
        result = self.response()
        self.assertEqual(result['totals']['documents'], 3, result)
        self.assertEqual((result['totals']['linked_plots'], result['totals']['mapped_plots']), (3, 2))
        plots = {item['plots'][0]['cadastral_id']: item['plots'][0] for item in result['items']}
        self.assertEqual(plots['68134.100.2']['lat'], 42.6)
        self.assertEqual(plots['68134.100.2']['catalogue_status'], 'current')
        self.assertEqual(plots['68134.100.3']['coordinate_method'], 'official_geometry_interior')
        self.assertEqual(plots[OLD]['catalogue_status'], 'not_in_latest_snapshot')
        self.assertIsNone(plots[OLD]['lat'])
        self.assertEqual(result['bounds'], dict(south=42.6, north=42.6, west=23.2015, east=23.203))
        self.assertTrue(result['parcel_catalogue']['available'])

    def test_page_hydration_does_not_limit_complete_matching_map_bounds(self):
        result = self.response({'limit': '1'})
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['cadastral_ids'], ['68134.100.2'])
        self.assertEqual(result['totals']['mapped_plots'], 2)
        self.assertEqual(result['bounds']['east'], 23.203)

    def test_historical_parent_only_view_has_no_current_map_coordinate(self):
        result = self.response({'q': OLD})
        self.assertEqual((result['totals']['documents'], result['totals']['mapped_plots']), (1, 0))
        self.assertIsNone(result['bounds'])
        self.assertEqual(result['items'][0]['cadastral_ids'], [OLD])
        self.assertIsNone(result['items'][0]['plots'][0]['lat'])

    def test_date_filter_changes_complete_matching_location_counts(self):
        result = self.response({'date_from': '2026-10-29'})
        self.assertEqual((result['totals']['documents'], result['totals']['mapped_plots']), (1, 1))
        self.assertEqual(result['items'][0]['plots'][0]['cadastral_id'], '68134.100.2')

    def test_unmappable_current_identifier_is_current_without_invented_point(self):
        registry = copy.deepcopy(self.registry)
        registry['documents'][0]['cadastral_ids'] = [UNMAPPED]
        result = self.response({'date_from': '2026-10-29'}, registry)
        plot = result['items'][0]['plots'][0]
        self.assertEqual(plot['catalogue_status'], 'current')
        self.assertEqual(plot['coordinate_method'], 'unavailable')
        self.assertIsNone(plot['lat'])
        self.assertEqual(result['totals']['mapped_plots'], 0)

    def test_legacy_v1_keeps_original_sql_location_fallback(self):
        manifest = copy.deepcopy(self.manifest); manifest['version'] = 1
        for field in ['catalogue', 'catalogue_count', 'mapped_point_count', 'unmapped_point_count', 'point_method']: manifest.pop(field)
        save_manifest(self.private, manifest)
        result = self.response()
        self.assertEqual(result['totals']['mapped_plots'], 1)
        self.assertEqual(result['bounds'], dict(south=42.75, north=42.75, west=23.45, east=23.45))
        parent = next(item for item in result['items'] if item['cadastral_ids'] == [OLD])
        self.assertEqual(parent['plots'][0]['lat'], 42.75)
        self.assertNotIn('catalogue_status', parent['plots'][0])
        self.assertFalse(result['parcel_catalogue']['available'])

    def test_corrupt_active_catalogue_cannot_create_partial_feed_success(self):
        path = self.folder / 'catalogue.tsv'
        path.write_bytes(path.read_bytes().replace(b'42.6000000', b'42.7000000', 1))
        self.assertIn('error', self.response())


if __name__ == '__main__': unittest.main()
