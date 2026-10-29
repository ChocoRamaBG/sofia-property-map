#!/usr/bin/env python3
"""Build full official parcel outlines from the 24 verified Sofia SHP exports.

Coordinates are transformed, never buffered, simplified, repaired or inferred
from the coordinate workbook. Native published AREA/PERIM remain separate from
map-display geometry. Invalid/conflicting parcel IDs are explicitly excluded.
Version 2 also retains every observed identifier in a complete catalogue;
verified interior map points and the unchanged polygons activate together.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4
from zipfile import ZipFile

from refresh_cadastre import archive_records, load_catalogue, official_download_url, timestamp_valid

REFERENCE_FORMAT = 'boundary-bbox-geojson-v1'
POINT_METHOD = 'strict_native_and_published_interior_v1'
MAX_MANIFEST_BYTES = 256 * 1024
MAX_INDEX_BYTES = 10000000
MAX_SHARD_BYTES = 1024 * 1024
MAX_DATASET_BYTES = 256 * 1024 * 1024
MAX_SHARDS = 1024
MAX_PARCELS = 500000
MAX_VERTICES = 10000000
MAX_FEATURE_VERTICES = 200000
MAX_FEATURE_BYTES = MAX_SHARD_BYTES - 100
SOURCE_URL = 'https://kais.cadastre.bg/bg/OpenData'
SOURCE_NAME = 'АГКК — КАИС, Отворени данни: поземлени имоти в гр. София'
CADASTRAL_ID = re.compile(r'68134\.[0-9]{1,6}\.[0-9]{1,6}')
SHARD_NAME = re.compile(r'boundaries-[0-9]{4}\.json')
HEX64 = re.compile(r'[a-f0-9]{64}')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(128 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def read_json(path: Path, limit: int = MAX_MANIFEST_BYTES):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
        raise ValueError('Boundary JSON file is absent, linked or exceeds its bound')
    def bad_constant(_):
        raise ValueError('Non-finite JSON number')
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=bad_constant)


def write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(payload)


def integer(value, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def valid_bounds(value) -> bool:
    return isinstance(value, list) and len(value) == 4 and all(finite(v) for v in value) and 22 <= value[0] <= value[2] <= 25 and 41 <= value[1] <= value[3] <= 44


def descriptor(value, name: str, limit: int, rows: str = 'rows') -> None:
    if not isinstance(value, dict) or value.get('file') != name or not integer(value.get('bytes'), 0, limit) or not isinstance(value.get('sha256'), str) or HEX64.fullmatch(value['sha256']) is None or not integer(value.get(rows), 0, MAX_PARCELS):
        raise ValueError('Invalid bounded boundary file descriptor')


def check_manifest(value: dict) -> dict:
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] not in (1, 2) or value.get('reference_format') != REFERENCE_FORMAT or re.fullmatch(r'[a-f0-9]{32}', str(value.get('snapshot_id', ''))) is None:
        raise ValueError('Invalid boundary snapshot identity')
    if not timestamp_valid(value.get('generated_at')) or not timestamp_valid(value.get('captured_at')) or value.get('source_url') != SOURCE_URL or value.get('source_name') != SOURCE_NAME:
        raise ValueError('Invalid official boundary provenance')
    if value.get('crs') != 'EPSG:4326' or value.get('native_crs') != 'EPSG:7801' or value.get('coordinate_precision') != 7 or value.get('index_precision') != 6 or value.get('min_zoom') != 16:
        raise ValueError('Unexpected boundary coordinate method')
    for field in ('record_count', 'parcel_count', 'feature_count', 'ambiguous_parcel_count', 'duplicate_observation_count', 'invalid_geometry_count', 'conflicting_parcel_count'):
        if not integer(value.get(field), 0, MAX_PARCELS):
            raise ValueError('Invalid boundary completion count')
    if value['feature_count'] != value['parcel_count'] or value['parcel_count'] < 1000 or value['ambiguous_parcel_count'] > max(5000, value['record_count'] * .05) or not integer(value.get('vertex_count'), 0, MAX_VERTICES):
        raise ValueError('Boundary geometry totals do not reconcile')
    descriptor(value.get('index'), 'boundaries.tsv', MAX_INDEX_BYTES)
    descriptor(value.get('ambiguous_index'), 'ambiguous.tsv', MAX_INDEX_BYTES)
    if value['index']['rows'] != value['parcel_count'] or value['ambiguous_index']['rows'] != value['ambiguous_parcel_count']:
        raise ValueError('Boundary indexes do not reconcile')
    catalogue_bytes = 0
    if value['version'] == 2:
        descriptor(value.get('catalogue'), 'catalogue.tsv', MAX_INDEX_BYTES)
        if value.get('point_method') != POINT_METHOD or not integer(value.get('catalogue_count'), 1000, MAX_PARCELS) or not integer(value.get('mapped_point_count'), 0, value['parcel_count']) or not integer(value.get('unmapped_point_count'), 0, MAX_PARCELS):
            raise ValueError('Official parcel catalogue counts or point method are invalid')
        if value['catalogue']['rows'] != value['catalogue_count'] or value['catalogue_count'] != value['parcel_count'] + value['ambiguous_parcel_count'] or value['catalogue_count'] > value['record_count'] or value['mapped_point_count'] + value['unmapped_point_count'] != value['catalogue_count'] or value['catalogue']['bytes'] <= 0:
            raise ValueError('Official parcel catalogue totals do not reconcile')
        catalogue_bytes = value['catalogue']['bytes']
    sources = value.get('sources')
    if not isinstance(sources, list) or len(sources) != 24:
        raise ValueError('All 24 official district exports are required')
    for position, source in enumerate(sources):
        if not isinstance(source, dict) or source.get('key') != f'sofia-district-{position:02}' or not isinstance(source.get('label_bg'), str) or not source['label_bg'].startswith('гр. София (68134) - район ') or len(source['label_bg']) > 200 or not timestamp_valid(source.get('captured_at')) or not integer(source.get('record_count'), 0, MAX_PARCELS):
            raise ValueError('Invalid official boundary source')
        official_download_url(source.get('source_url'))
        if any(not isinstance(source.get(field), str) or HEX64.fullmatch(source[field]) is None for field in ('archive_sha256', 'projection_sha256')):
            raise ValueError('Boundary source hash is missing')
    if sum(source['record_count'] for source in sources) != value['record_count']:
        raise ValueError('Boundary source row total does not reconcile')
    shards = value.get('shards')
    if not isinstance(shards, list) or not 1 <= len(shards) <= MAX_SHARDS:
        raise ValueError('Invalid boundary shard count')
    for position, shard in enumerate(shards):
        descriptor(shard, f'boundaries-{position:04}.json', MAX_SHARD_BYTES, 'feature_count')
        if shard['bytes'] <= 0 or shard['feature_count'] <= 0 or not integer(shard.get('vertex_count'), 1, MAX_VERTICES) or not valid_bounds(shard.get('bounds')):
            raise ValueError('Invalid boundary shard geometry envelope')
    if sum(s['feature_count'] for s in shards) != value['parcel_count'] or sum(s['vertex_count'] for s in shards) != value['vertex_count']:
        raise ValueError('Boundary shard totals do not reconcile')
    if sum(s['bytes'] for s in shards) + value['index']['bytes'] + value['ambiguous_index']['bytes'] + catalogue_bytes > MAX_DATASET_BYTES:
        raise ValueError('Boundary snapshot exceeds its total byte limit')
    completion = value.get('completion')
    if not isinstance(completion, dict) or completion.get('status') != 'complete' or completion.get('source_count') != 24 or completion.get('record_count') != value['record_count']:
        raise ValueError('Boundary capture is incomplete')
    return value


def verified_lines(root: Path, info: dict):
    """Stream one exact bounded private index, verifying it on exhaustion."""
    path = Path(root) / info['file']
    if path.is_symlink() or not path.is_file() or path.stat().st_size != info['bytes'] or info['bytes'] > MAX_INDEX_BYTES:
        raise ValueError('Official parcel index is absent, linked or exceeds its byte bound')
    checksum, total = hashlib.sha256(), 0
    with path.open('rb') as handle:
        for raw in handle:
            total += len(raw)
            checksum.update(raw)
            if total > info['bytes'] or len(raw) > 256 or not raw.endswith(b'\n'):
                raise ValueError('Official parcel index has an invalid bounded line')
            yield raw[:-1].decode('ascii')
    if total != info['bytes'] or checksum.hexdigest() != info['sha256']:
        raise ValueError('Official parcel index failed its bytes or SHA-256 check')


def catalogue_rows(root: Path, manifest: dict):
    """Yield complete v2 rows: ID, latitude, longitude, first source, status.

    The source ordinal is the first (lowest) observing district. Conflicting
    observations retain all source capture evidence in the manifest and never
    produce a point. Consumers must exhaust the iterator to verify its hash.
    """
    check_manifest(manifest)
    if manifest.get('version') != 2:
        raise ValueError('The legacy boundary snapshot has no point catalogue')
    previous, rows, mapped = '', 0, 0
    for line in verified_lines(root, manifest['catalogue']):
        fields = line.split('\t')
        if len(fields) != 5 or CADASTRAL_ID.fullmatch(fields[0]) is None or fields[0] <= previous or not re.fullmatch(r'(?:[0-9]|1[0-9]|2[0-3])', fields[3]) or fields[4] not in ('mapped', 'unavailable'):
            raise ValueError('Official parcel catalogue row is invalid or not unique and sorted')
        if fields[4] == 'mapped':
            if not all(re.fullmatch(r'[0-9]{2}\.[0-9]{7}', x) for x in fields[1:3]):
                raise ValueError('Official parcel point precision is invalid')
            lat, lng = map(float, fields[1:3])
            if not valid_bounds([lng, lat, lng, lat]):
                raise ValueError('Official parcel point is outside supported Sofia bounds')
            mapped += 1
        else:
            if fields[1] or fields[2]:
                raise ValueError('An unavailable official parcel cannot publish coordinates')
            lat = lng = None
        if manifest['sources'][int(fields[3])]['record_count'] < 1:
            raise ValueError('The catalogue refers to an empty official source')
        rows += 1
        if rows > manifest['catalogue_count']:
            raise ValueError('Official parcel catalogue exceeds its declared row count')
        yield fields[0], lat, lng, int(fields[3]), fields[4]
        previous = fields[0]
    if rows != manifest['catalogue_count'] or mapped != manifest['mapped_point_count'] or rows - mapped != manifest['unmapped_point_count']:
        raise ValueError('Official parcel catalogue completion counts disagree')


def catalogue_ids(root: Path, manifest: dict) -> set[str]:
    """Read the complete source-observed ID set, including legacy exclusions."""
    check_manifest(manifest)
    if manifest['version'] == 2:
        return {row[0] for row in catalogue_rows(root, manifest)}
    identifiers, previous, count = set(), '', 0
    for line in verified_lines(root, manifest['index']):
        fields = line.split('\t')
        if len(fields) != 6 or CADASTRAL_ID.fullmatch(fields[0]) is None or fields[0] <= previous or not fields[5].isdigit():
            raise ValueError('Previous official boundary index is invalid')
        south, north, west, east = map(float, fields[1:5])
        if not valid_bounds([west, south, east, north]) or not 0 <= int(fields[5]) < len(manifest['shards']):
            raise ValueError('Previous official boundary envelope is invalid')
        identifiers.add(fields[0]); previous = fields[0]; count += 1
    if count != manifest['parcel_count']:
        raise ValueError('Previous official boundary catalogue is incomplete')
    previous, count = '', 0
    for key in verified_lines(root, manifest['ambiguous_index']):
        if CADASTRAL_ID.fullmatch(key) is None or key <= previous or key in identifiers:
            raise ValueError('Previous official excluded identifier is invalid')
        identifiers.add(key); previous = key; count += 1
    if count != manifest['ambiguous_parcel_count']:
        raise ValueError('Previous official exclusion catalogue is incomplete')
    return identifiers


def verified_interior_point(native, display, transformer):
    """Derive a point and verify its published rounded coordinates twice.

    No geometry is repaired or altered. An unsuitable interior point leaves the
    ID in the current catalogue with unavailable coordinates.
    """
    from shapely.geometry import Point
    from shapely.errors import GEOSException
    from pyproj.exceptions import ProjError
    try:
        candidate = native.representative_point()
        if native.is_empty or display.is_empty or not native.is_valid or not display.is_valid or not native.contains(candidate):
            return None
        lng, lat = transformer.transform(candidate.x, candidate.y, errcheck=True) if transformer is not None else (candidate.x, candidate.y)
        lng, lat = round(lng, 7), round(lat, 7)
        if not valid_bounds([lng, lat, lng, lat]) or not display.contains(Point(lng, lat)):
            return None
        x, y = transformer.transform(lng, lat, direction='INVERSE', errcheck=True) if transformer is not None else (lng, lat)
        if not all(math.isfinite(v) for v in (x, y)) or not native.contains(Point(x, y)):
            return None
        return lat, lng
    except (ValueError, TypeError, IndexError, OverflowError, GEOSException, ProjError):
        return None


def geometry_vertices(geometry: dict) -> tuple[int, list[float]]:
    if not isinstance(geometry, dict) or geometry.get('type') not in ('Polygon', 'MultiPolygon'):
        raise ValueError('Only complete polygon boundaries are permitted')
    polygons = [geometry.get('coordinates')] if geometry['type'] == 'Polygon' else geometry.get('coordinates')
    if not isinstance(polygons, list) or not polygons:
        raise ValueError('Boundary polygon is empty')
    count = 0
    bounds = [180., 90., -180., -90.]
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError('Boundary polygon rings are empty')
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError('Boundary rings must be closed')
            for point in ring:
                if not isinstance(point, list) or len(point) != 2 or not all(finite(v) for v in point) or not 22 <= point[0] <= 25 or not 41 <= point[1] <= 44:
                    raise ValueError('Boundary coordinates are outside Sofia')
                count += 1
                bounds = [min(bounds[0], point[0]), min(bounds[1], point[1]), max(bounds[2], point[0]), max(bounds[3], point[1])]
    if not 4 <= count <= MAX_FEATURE_VERTICES:
        raise ValueError('Boundary vertex count exceeds its bound')
    return count, bounds


def validate_publish_tree(root: Path) -> dict:
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Boundary publication root is absent or linked')
    manifest = check_manifest(read_json(root / 'manifest.json'))
    names = {'manifest.json', manifest['index']['file'], manifest['ambiguous_index']['file'], *[s['file'] for s in manifest['shards']]}
    descriptors = [manifest['index'], manifest['ambiguous_index'], *manifest['shards']]
    if manifest['version'] == 2:
        names.add(manifest['catalogue']['file'])
        descriptors.append(manifest['catalogue'])
    if {p.name for p in root.iterdir()} != names:
        raise ValueError('Unexpected or missing boundary publication files')
    index = {}
    for info in descriptors:
        path = root / info['file']
        if path.is_symlink() or not path.is_file() or path.stat().st_size != info['bytes'] or file_digest(path) != info['sha256']:
            raise ValueError('Boundary file failed its size or SHA-256 check')
    previous = ''
    for line in (root / manifest['index']['file']).read_text(encoding='utf-8').splitlines():
        fields = line.split('\t')
        if len(fields) != 6 or CADASTRAL_ID.fullmatch(fields[0]) is None or fields[0] <= previous or not fields[5].isdigit():
            raise ValueError('Boundary index is invalid or not unique and sorted')
        south, north, west, east = map(float, fields[1:5])
        shard = int(fields[5])
        if not valid_bounds([west, south, east, north]) or not 0 <= shard < len(manifest['shards']):
            raise ValueError('Boundary index envelope or shard is invalid')
        index[fields[0]] = ([west, south, east, north], shard)
        previous = fields[0]
    if len(index) != manifest['parcel_count']:
        raise ValueError('Boundary index row count does not reconcile')
    ambiguous = (root / manifest['ambiguous_index']['file']).read_text(encoding='utf-8').splitlines()
    if ambiguous != sorted(set(ambiguous)) or any(CADASTRAL_ID.fullmatch(key) is None or key in index for key in ambiguous) or len(ambiguous) != manifest['ambiguous_parcel_count']:
        raise ValueError('Unusable boundary identifiers do not reconcile')
    catalogue = {row[0]: row[1:] for row in catalogue_rows(root, manifest)} if manifest['version'] == 2 else None
    if catalogue is not None and set(catalogue) != set(index) | set(ambiguous):
        raise ValueError('The official catalogue omits or invents observed identifiers')
    if catalogue is not None and any(catalogue[key][3] != 'unavailable' for key in ambiguous):
        raise ValueError('An unusable geometry identifier cannot have an official interior point')
    seen = set()
    for position, info in enumerate(manifest['shards']):
        data = read_json(root / info['file'], MAX_SHARD_BYTES)
        if data.get('type') != 'FeatureCollection' or not isinstance(data.get('features'), list) or len(data['features']) != info['feature_count']:
            raise ValueError('Boundary shard is not a complete feature collection')
        total = 0
        shard_bounds = None
        for feature in data['features']:
            key = feature.get('id')
            props = feature.get('properties')
            vertices, bbox = geometry_vertices(feature.get('geometry'))
            if feature.get('type') != 'Feature' or key not in index or key in seen or index[key][1] != position or feature.get('bbox') != bbox or not bbox_contains(index[key][0], bbox) or not isinstance(props, dict) or props.get('cadastral_id') != key or props.get('vertex_count') != vertices or props.get('native_crs') != 'BGS2005_LCC' or props.get('source_key') not in {source['key'] for source in manifest['sources']}:
                raise ValueError('Boundary feature/index relationship is invalid')
            if set(props) != {'cadastral_id', 'area_m2', 'perimeter_m', 'source_key', 'vertex_count', 'native_crs'} or not finite(props['area_m2']) or props['area_m2'] <= 0 or not finite(props['perimeter_m']) or props['perimeter_m'] <= 0:
                raise ValueError('Boundary properties are invalid or exceed their allowlist')
            if catalogue is not None:
                from shapely.geometry import Point, shape
                lat, lng, source, status = catalogue[key]
                if props['source_key'] != f'sofia-district-{source:02}':
                    raise ValueError('The official parcel point and geometry source disagree')
                if status == 'mapped' and not shape(feature['geometry']).contains(Point(lng, lat)):
                    raise ValueError('Published official point is not strictly inside its complete polygon')
            seen.add(key)
            total += vertices
            shard_bounds = bbox if shard_bounds is None else [min(shard_bounds[0], bbox[0]), min(shard_bounds[1], bbox[1]), max(shard_bounds[2], bbox[2]), max(shard_bounds[3], bbox[3])]
        if total != info['vertex_count'] or shard_bounds != info['bounds']:
            raise ValueError('Boundary shard vertices do not reconcile')
    if len(seen) != manifest['parcel_count']:
        raise ValueError('Boundary features are incomplete')
    return manifest


def projection(prj: str):
    from pyproj import CRS, Transformer, network
    network.set_network_enabled(False)
    if 'PROJCS["BGS2005"' not in prj or len(prj) > 8192:
        raise ValueError('Unexpected published parcel projection')
    source = CRS.from_wkt(prj)
    native = CRS.from_epsg(7801)
    if abs(source.ellipsoid.semi_major_metre - native.ellipsoid.semi_major_metre) > .000001 or abs(source.ellipsoid.inverse_flattening - native.ellipsoid.inverse_flattening) > .000001:
        raise ValueError('Published parcel ellipsoid differs from BGS2005')
    actual = {p.name: p.value for p in source.coordinate_operation.params}
    expected = {p.name: p.value for p in native.coordinate_operation.params}
    if set(actual) != set(expected) or any(abs(actual[key] - expected[key]) > 1e-8 for key in actual):
        raise ValueError('Published parcel projection differs from EPSG:7801')
    if any(axis.unit_name != 'metre' for axis in source.axis_info):
        raise ValueError('Published parcel coordinates are not in metres')
    transform = Transformer.from_crs(native, CRS.from_epsg(4326), always_xy=True, allow_ballpark=False)
    if transform.accuracy < 0 or transform.accuracy > 1:
        raise ValueError('No supported non-ballpark BGS2005 to WGS84 operation')
    return transform


def transform_geometry(value: dict, transformer) -> dict:
    def ring(points):
        x, y = zip(*[(p[0], p[1]) for p in points])
        lon, lat = transformer.transform(x, y, errcheck=True)
        return [[round(a, 7), round(b, 7)] for a, b in zip(lon, lat)]
    if value['type'] == 'Polygon':
        coordinates = [ring(points) for points in value['coordinates']]
    elif value['type'] == 'MultiPolygon':
        coordinates = [[ring(points) for points in polygon] for polygon in value['coordinates']]
    else:
        raise ValueError('Published shape is not a polygon')
    return {'type': value['type'], 'coordinates': coordinates}


def build(catalogue_path: Path, archives: Path, output: Path) -> dict:
    import shapefile
    from shapely.geometry import shape
    from shapely.validation import explain_validity
    catalogue, catalogue_hash = load_catalogue(catalogue_path)
    if output.exists() or output.is_symlink():
        raise ValueError('Boundary output must be a new directory')
    output.mkdir(parents=True)
    work = output.parent / f'boundary-{uuid4().hex}.work.sqlite'
    connection = sqlite3.connect(work)
    connection.execute('CREATE TABLE observations (id TEXT PRIMARY KEY, identity TEXT, feature BLOB, bbox TEXT, vertices INTEGER, unusable INTEGER NOT NULL DEFAULT 0, conflict INTEGER NOT NULL DEFAULT 0, latitude REAL, longitude REAL, source_ordinal INTEGER NOT NULL)')
    sources = []
    record_count = duplicates = invalid = 0
    invalid_reasons = {}
    try:
        for position, source in enumerate(catalogue['sources']):
            source_key = f'sofia-district-{position:02}'
            path = archives / f'{source_key}.zip'
            evidence = read_json(path.with_suffix('.download.json'))
            url = official_download_url(source['download_path'])
            if evidence.get('version') != 1 or evidence.get('source_url') != url or not timestamp_valid(evidence.get('captured_at')) or evidence.get('zip_bytes') != path.stat().st_size or evidence.get('zip_sha256') != file_digest(path):
                raise ValueError('Official boundary archive does not match its verified capture')
            district = source['label_bg'].split(' - ', 1)[1]
            row_count = 0
            with ZipFile(path) as archive:
                entries = archive.infolist()
                shape_entries = [entry for entry in entries if entry.filename.lower().endswith('.shp')]
                if len(shape_entries) != 1:
                    raise ValueError('One official parcel SHP is required')
                shp = shape_entries[0]
                stem = shp.filename[:-4]
                lookup = {entry.filename: entry for entry in entries}
                for suffix in ('.shx', '.prj', '.dbf', '.cpg'):
                    if stem + suffix not in lookup:
                        raise ValueError('Published shape companion is missing')
                if shp.file_size > 256 * 1024 * 1024 or lookup[stem + '.shx'].file_size > 8 * 1024 * 1024:
                    raise ValueError('Boundary SHP/SHX exceeds its byte limit')
                prj = archive.read(stem + '.prj').decode('utf-8')
                transformer = projection(prj)
                with archive.open(shp) as shp_file, archive.open(stem + '.shx') as shx_file:
                    reader = shapefile.Reader(shp=shp_file, shx=shx_file)
                    shapes = reader.iterShapes()
                    perimeters = iter_perimeters(path)
                    for key, area_text, record in archive_records(path, district):
                        try:
                            geometry_shape = next(shapes)
                        except StopIteration as error:
                            raise ValueError('SHP has fewer records than its verified DBF') from error
                        row_count += 1
                        record_count += 1
                        original_perimeter = next(perimeters)
                        if record_count > MAX_PARCELS:
                            raise ValueError('Boundary record limit exceeded')
                        reason = None
                        point = None
                        try:
                            if geometry_shape.shapeType != shapefile.POLYGON or not 4 <= len(geometry_shape.points) <= MAX_FEATURE_VERTICES:
                                raise ValueError('unsupported_shape_or_vertex_count')
                            native_geojson = geometry_shape.__geo_interface__
                            native_shape = shape(native_geojson)
                            if native_shape.is_empty or not native_shape.is_valid:
                                raise ValueError('invalid_native_topology:' + explain_validity(native_shape))
                            # The identity compares original native geometry AND
                            # all allowed cadastral attributes, not just its area.
                            identity = digest(native_shape.normalize().wkb + b'\0' + json_bytes(record) + b'\0' + json_bytes(original_perimeter))
                            transformed = transform_geometry(native_geojson, transformer)
                            transformed_shape = shape(transformed)
                            if transformed_shape.is_empty or not transformed_shape.is_valid:
                                raise ValueError('invalid_transformed_topology:' + explain_validity(transformed_shape))
                            vertices, bbox = geometry_vertices(transformed)
                            # PERIM is preserved from the official DBF separately
                            # from the transformed map outline; no edge is inferred.
                            feature = {'type': 'Feature', 'id': key, 'bbox': bbox, 'geometry': transformed, 'properties': {'cadastral_id': key, 'area_m2': float(area_text), 'perimeter_m': original_perimeter, 'source_key': source_key, 'vertex_count': vertices, 'native_crs': 'BGS2005_LCC'}}
                            payload = json_bytes(feature)
                            if len(payload) > MAX_FEATURE_BYTES:
                                raise ValueError('oversized_feature')
                            point = verified_interior_point(native_shape, transformed_shape, transformer)
                        except (ValueError, TypeError, IndexError, OverflowError) as error:
                            reason = str(error).split(':', 1)[0]
                            invalid += 1
                            invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1
                            identity, payload, bbox, vertices = '', b'', [], 0
                        previous = connection.execute('SELECT identity, unusable FROM observations WHERE id=?', (key,)).fetchone()
                        if previous is None:
                            connection.execute('INSERT INTO observations(id,identity,feature,bbox,vertices,unusable,latitude,longitude,source_ordinal) VALUES(?,?,?,?,?,?,?,?,?)', (key, identity, payload, json.dumps(bbox), vertices, int(reason is not None), point[0] if point else None, point[1] if point else None, position))
                        elif reason is not None or previous[1] or previous[0] != identity:
                            connection.execute('UPDATE observations SET feature=NULL,bbox=NULL,vertices=0,latitude=NULL,longitude=NULL,unusable=1,conflict=CASE WHEN ? THEN conflict ELSE 1 END WHERE id=?', (int(reason is not None or previous[1]), key))
                        else:
                            duplicates += 1
                    if next(shapes, None) is not None or next(perimeters, None) is not None:
                        raise ValueError('SHP has more records than its verified DBF')
                    reader.close()
            connection.commit()
            sources.append({'key': source_key, 'label_bg': source['label_bg'], 'source_url': url, 'captured_at': evidence['captured_at'], 'archive_sha256': evidence['zip_sha256'], 'catalogue_published_at': source.get('published_at'), 'http_last_modified': evidence.get('published_at'), 'record_count': row_count, 'projection_sha256': digest(prj.encode('utf-8'))})
            print(f'Prepared {source_key}: {row_count} official parcel records', flush=True)
        manifest = finish_snapshot(connection, output, sources, record_count, duplicates, invalid, invalid_reasons, catalogue_hash)
    finally:
        connection.close()
        work.unlink(missing_ok=True)
    validate_publish_tree(output)
    return manifest


def iter_perimeters(path: Path):
    """Read only the publisher's native PERIM field; never owner data."""
    with ZipFile(path) as archive:
        dbf = next(entry for entry in archive.infolist() if entry.filename.lower().endswith('.dbf'))
        with archive.open(dbf) as handle:
            header = handle.read(32)
            count = struct.unpack('<I', header[4:8])[0]
            header_length, record_length = struct.unpack('<HH', header[8:12])
            position, perim = 1, None
            for _ in range((header_length - 33) // 32):
                raw = handle.read(32)
                name = raw[:11].split(b'\0')[0].decode('ascii')
                if name == 'PERIM':
                    perim = (position, raw[16])
                position += raw[16]
            if perim is None or position != record_length or handle.read(1) != b'\r':
                raise ValueError('Published PERIM field is absent or malformed')
            for _ in range(count):
                row = handle.read(record_length)
                if len(row) != record_length or row[:1] != b' ':
                    raise ValueError('Published perimeter row is malformed')
                text = row[perim[0]:perim[0] + perim[1]].decode('ascii').strip()
                if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', text) is None:
                    raise ValueError('Published PERIM is not a positive native metre value')
                value = float(text)
                if not math.isfinite(value) or not 0 < value <= 1000000000:
                    raise ValueError('Published PERIM is outside its supported metre bounds')
                yield value


def index_bbox(bbox):
    return [math.floor(bbox[0] * 1000000) / 1000000, math.floor(bbox[1] * 1000000) / 1000000,
            math.ceil(bbox[2] * 1000000) / 1000000, math.ceil(bbox[3] * 1000000) / 1000000]


def bbox_contains(outer, inner):
    if not valid_bounds(outer):
        return False
    differences = [inner[0] - outer[0], inner[1] - outer[1], outer[2] - inner[2], outer[3] - inner[3]]
    return all(-1e-10 <= value <= 1.0001e-6 for value in differences)


def finish_snapshot(connection, output, sources, record_count, duplicates, invalid, reasons, catalogue_hash):
    shards = []
    index_lines = []
    current = []
    size = len(b'{"type":"FeatureCollection","features":[]}')
    vertices = 0
    bounds = None
    def flush():
        nonlocal current, size, vertices, bounds
        if not current:
            return
        if len(shards) >= MAX_SHARDS:
            raise ValueError('Boundary shard count exceeds its limit')
        name = f'boundaries-{len(shards):04}.json'
        payload = b'{"type":"FeatureCollection","features":[' + b','.join(current) + b']}'
        if len(payload) > MAX_SHARD_BYTES:
            raise ValueError('Boundary shard exceeds its byte limit')
        write_new(output / name, payload)
        shards.append({'file': name, 'bytes': len(payload), 'sha256': digest(payload), 'feature_count': len(current), 'vertex_count': vertices, 'bounds': bounds})
        current, size, vertices, bounds = [], len(b'{"type":"FeatureCollection","features":[]}'), 0, None
    for key, feature, encoded_bbox, vertex_count in connection.execute('SELECT id,feature,bbox,vertices FROM observations WHERE unusable=0 ORDER BY id'):
        if current and size + len(feature) + 1 > MAX_SHARD_BYTES:
            flush()
        bbox = json.loads(encoded_bbox)
        lookup_bbox = index_bbox(bbox)
        index_lines.append(f'{key}\t{lookup_bbox[1]:.6f}\t{lookup_bbox[3]:.6f}\t{lookup_bbox[0]:.6f}\t{lookup_bbox[2]:.6f}\t{len(shards)}\n')
        current.append(feature)
        size += len(feature) + 1
        vertices += vertex_count
        bounds = bbox if bounds is None else [min(bounds[0], bbox[0]), min(bounds[1], bbox[1]), max(bounds[2], bbox[2]), max(bounds[3], bbox[3])]
    flush()
    index_payload = ''.join(index_lines).encode('utf-8')
    unusable = [row[0] for row in connection.execute('SELECT id FROM observations WHERE unusable=1 ORDER BY id')]
    ambiguous_payload = ''.join(key + '\n' for key in unusable).encode('utf-8')
    if len(index_payload) > MAX_INDEX_BYTES or len(ambiguous_payload) > MAX_INDEX_BYTES:
        raise ValueError('Boundary lookup index exceeds its byte limit')
    write_new(output / 'boundaries.tsv', index_payload)
    write_new(output / 'ambiguous.tsv', ambiguous_payload)
    catalogue_lines, mapped_points = [], 0
    for key, lat, lng, source, is_unusable in connection.execute('SELECT id,latitude,longitude,source_ordinal,unusable FROM observations ORDER BY id'):
        if not integer(source, 0, 23) or CADASTRAL_ID.fullmatch(key) is None or ((lat is None) != (lng is None)) or (is_unusable and lat is not None):
            raise ValueError('The prepared official parcel catalogue is inconsistent')
        if lat is not None:
            if not valid_bounds([lng, lat, lng, lat]):
                raise ValueError('The prepared official parcel point is out of bounds')
            catalogue_lines.append(f'{key}\t{lat:.7f}\t{lng:.7f}\t{source}\tmapped\n')
            mapped_points += 1
        else:
            catalogue_lines.append(f'{key}\t\t\t{source}\tunavailable\n')
    catalogue_payload = ''.join(catalogue_lines).encode('ascii')
    if len(catalogue_payload) > MAX_INDEX_BYTES:
        raise ValueError('Official parcel catalogue exceeds the hosting file limit')
    write_new(output / 'catalogue.tsv', catalogue_payload)
    total_vertices = sum(s['vertex_count'] for s in shards)
    manifest = {'version': 1, 'reference_format': REFERENCE_FORMAT, 'snapshot_id': uuid4().hex, 'generated_at': utc_now(), 'captured_at': max(s['captured_at'] for s in sources), 'source_name': SOURCE_NAME, 'source_url': SOURCE_URL, 'catalogue_sha256': catalogue_hash, 'crs': 'EPSG:4326', 'native_crs': 'EPSG:7801', 'coordinate_precision': 7, 'index_precision': 6, 'transform_accuracy_m': 1.0, 'min_zoom': 16, 'geometry_method': 'Full official polygon vertices transformed without simplification or repair; 7 decimal WGS84 display coordinates.', 'record_count': record_count, 'parcel_count': len(index_lines), 'feature_count': len(index_lines), 'ambiguous_parcel_count': len(unusable), 'duplicate_observation_count': duplicates, 'invalid_geometry_count': invalid, 'conflicting_parcel_count': connection.execute('SELECT COUNT(*) FROM observations WHERE conflict=1').fetchone()[0], 'invalid_geometry_reasons': reasons, 'vertex_count': total_vertices, 'index': {'file': 'boundaries.tsv', 'bytes': len(index_payload), 'sha256': digest(index_payload), 'rows': len(index_lines)}, 'ambiguous_index': {'file': 'ambiguous.tsv', 'bytes': len(ambiguous_payload), 'sha256': digest(ambiguous_payload), 'rows': len(unusable)}, 'shards': shards, 'sources': sources, 'completion': {'status': 'complete', 'source_count': len(sources), 'record_count': record_count}, 'notes': ['Official published cadastral snapshot geometry, not a certified current cadastral sketch or field survey.', 'Published AREA and PERIM use the native metre projection. The WGS84 display transform declares 1 metre operation accuracy.', 'Unusable IDs include conflicting original records and invalid polygons. Original geometries are never repaired, simplified, buffered or inferred.']}
    manifest.update(version=2, catalogue={'file': 'catalogue.tsv', 'bytes': len(catalogue_payload), 'sha256': digest(catalogue_payload), 'rows': len(catalogue_lines)}, catalogue_count=len(catalogue_lines), mapped_point_count=mapped_points, unmapped_point_count=len(catalogue_lines) - mapped_points, point_method=POINT_METHOD)
    manifest['notes'].append('The complete observed identifier catalogue and verified interior points activate with these boundaries. Missing identifiers in a later complete capture are not a legal retirement or successor determination.')
    check_manifest(manifest)
    payload = json_bytes(manifest)
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError('Boundary manifest exceeds its byte limit')
    write_new(output / 'manifest.json', payload)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalogue', type=Path, required=True)
    parser.add_argument('--archives', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.catalogue, args.archives, args.output)
    print(f"Prepared complete boundary snapshot {result['snapshot_id']}: {result['parcel_count']} parcels, {result['ambiguous_parcel_count']} unavailable IDs, {len(result['shards'])} shards, {result['vertex_count']} vertices")
    print(f"Prepared current official identifier catalogue: {result['catalogue_count']} IDs, {result['mapped_point_count']} verified interior points, {result['unmapped_point_count']} IDs without a usable point; {result['catalogue']['bytes']} catalogue bytes")


if __name__ == '__main__':
    main()
