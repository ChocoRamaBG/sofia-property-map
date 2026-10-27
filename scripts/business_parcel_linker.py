"""Conservative offline containment of official address points in KAIS parcels.

Every point for one municipal address must be strictly inside the same unique
valid parcel in both native geometry and the published display geometry. This
module never geocodes, buffers, repairs, snaps, or chooses a nearest parcel.
Geometry dependencies are imported only when an index is built or queried.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from build_boundary_snapshot import (
    CADASTRAL_ID, MAX_FEATURE_BYTES, MAX_FEATURE_VERTICES, MAX_PARCELS,
    MAX_VERTICES, file_digest, geometry_vertices, json_bytes, projection,
    read_json, transform_geometry,
)
from refresh_cadastre import archive_records, official_download_url, timestamp_valid

# Exact code/label pairs observed in the verified 24-district October capture.
# 2280 (vehicle repair/maintenance) is deliberately not a road or railway.
TRANSPORT_USES = {
    '2100': 'За първостепенна улица',
    '2110': 'За второстепенна улица',
    '2170': 'За линии на релсов транспорт',
    '2180': 'За депо за релсов транспорт',
    '2210': 'За път от републиканската пътна мрежа',
    '2220': 'За местен път',
    '2230': 'За селскостопански, горски, ведомствен път',
    '2270': 'За железопътна гара, спирка',
    '2310': 'За друг поземлен имот за движение и транспорт',
    '3100': 'Водно течение, река',
    '3240': 'За водностопанско, хидромелиоративно съоръжение',
    '3250': 'За друг вид водно течение, водна площ, съоръжение',
}
REFERENCE_ID = re.compile(r'[A-Za-z0-9_.:/-]{1,160}\Z')
MAX_ADDRESS_POINTS = 1024


def non_address_use(properties):
    code, label = str(properties.get('use_code') or ''), str(properties.get('use') or '').strip()
    # A reused known code with a different label needs review, not acceptance.
    if code in TRANSPORT_USES:
        return 'road' if label == TRANSPORT_USES[code] else 'conflict'
    if label in TRANSPORT_USES.values():
        return 'road' if code in TRANSPORT_USES else 'conflict'
    if re.search(r'\b(?:улица|път|пътна|пътно|пътни|релсов|железопътна|железопътен|автомагистрала|магистрала|водно течение)\b', label.casefold()):
        # A previously unseen transport label is held for review; this does
        # not invent an official classification code for future captures.
        return 'conflict'
    return None


@dataclass
class Parcel:
    cadastral_id: str
    native: object
    display: object
    transformer: object = None
    properties: dict = None
    identity: str = ''
    blocker: bool = False


class ParcelLinker:
    """In-memory STRtree; constructor also supports small synthetic fixtures."""

    def __init__(self, parcels, excluded_ids=(), provenance=None, counts=None):
        from shapely.strtree import STRtree
        self.provenance = provenance or {}
        self.counts = dict(counts or {})
        self.excluded_ids = set(excluded_ids)
        grouped = defaultdict(list)
        for parcel in parcels:
            if CADASTRAL_ID.fullmatch(parcel.cadastral_id) is None:
                raise ValueError('Invalid parcel identifier')
            if parcel.display.is_empty or not parcel.display.is_valid:
                raise ValueError('Index display geometry must be valid; use a blocking envelope for invalid observations')
            grouped[parcel.cadastral_id].append(parcel)
        self.conflicting_ids = set(self.excluded_ids)
        self.parcels = []
        self.by_id = {}
        for identifier, observations in grouped.items():
            identities = {p.identity or hashlib.sha256((p.native.normalize().wkb if p.native is not None else b'') + b'\0' + p.display.normalize().wkb + b'\0' + json_bytes(p.properties or {})).hexdigest() for p in observations}
            if len(identities) != 1 or any(p.blocker for p in observations):
                self.conflicting_ids.add(identifier)
            # Identical duplicated observations do not create extra candidates.
            seen = set()
            for observation in observations:
                identity = (observation.display.normalize().wkb, observation.blocker)
                if identity in seen:
                    continue
                seen.add(identity)
                self.parcels.append(observation)
            if identifier not in self.conflicting_ids:
                self.by_id[identifier] = observations[0]
        self.tree = STRtree([p.display for p in self.parcels])
        self.counts.update(index_observations=len(self.parcels), usable_parcels=len(self.by_id), excluded_or_conflicting_ids=len(self.conflicting_ids))

    def representative_point(self, identifier):
        """Return a verified interior display point, never a centroid guess."""
        from shapely.geometry import Point
        parcel = self.by_id.get(identifier)
        if parcel is None or non_address_use(parcel.properties or {}):
            return None
        point = parcel.native.representative_point()
        if not parcel.native.contains(point):
            return None
        lng, lat = parcel.transformer.transform(point.x, point.y, errcheck=True) if parcel.transformer is not None else (point.x, point.y)
        if not all(math.isfinite(x) for x in (lng, lat)) or not parcel.display.contains(Point(lng, lat)):
            return None
        return {'lat': lat, 'lng': lng}

    def properties(self, identifier):
        parcel = self.by_id.get(identifier)
        return dict(parcel.properties or {}) if parcel else None

    def _point(self, lat, lng):
        from shapely.geometry import Point
        point = Point(lng, lat)
        inside, boundary, conflict, roads = set(), set(), set(), set()
        for index in self.tree.query(point):
            parcel = self.parcels[int(index)]
            if not parcel.display.intersects(point):
                continue
            identifier = parcel.cadastral_id
            if identifier in self.conflicting_ids or parcel.blocker:
                conflict.add(identifier)
                continue
            if parcel.transformer is None:
                native_point = point
            else:
                from pyproj.enums import TransformDirection
                x, y = parcel.transformer.transform(lng, lat, direction=TransformDirection.INVERSE, errcheck=True)
                native_point = Point(x, y)
            if not parcel.display.contains(point) or not parcel.native.contains(native_point):
                boundary.add(identifier)
                continue
            classification = non_address_use(parcel.properties or {})
            if classification == 'conflict':
                conflict.add(identifier)
            elif classification == 'road':
                roads.add(identifier)
            else:
                inside.add(identifier)
        if conflict:
            return 'conflict', None
        if boundary:
            return 'boundary', None
        if roads:
            return 'road', None
        if len(inside) > 1:
            return 'ambiguous', None
        if not inside:
            return 'outside', None
        return 'unique', next(iter(inside))

    def resolve(self, points):
        """Resolve ALL distinct points of one official address, or none of them."""
        result = {'status': 'outside', 'cadastral_id': None, 'reference_ids': [], 'point_count': 0}
        if not isinstance(points, list) or len(points) > MAX_ADDRESS_POINTS:
            return {**result, 'status': 'conflict', 'reason': 'invalid_point_collection'}
        unique, references = set(), set()
        for value in points:
            if not isinstance(value, dict) or any(type(value.get(k)) not in (int, float) or not math.isfinite(value[k]) for k in ('lat', 'lng')) or not -90 <= value['lat'] <= 90 or not -180 <= value['lng'] <= 180:
                return {**result, 'status': 'conflict', 'reason': 'invalid_address_point'}
            reference = value.get('reference_id')
            if isinstance(reference, int) and not isinstance(reference, bool) and reference >= 0:
                reference = str(reference)
            if not isinstance(reference, str) or REFERENCE_ID.fullmatch(reference) is None:
                return {**result, 'status': 'conflict', 'reason': 'invalid_reference_id'}
            references.add(reference)
            unique.add((value['lat'], value['lng']))
        result.update(reference_ids=sorted(references), point_count=len(unique))
        if not unique:
            return {**result, 'reason': 'no_address_points'}
        observations = [self._point(lat, lng) for lat, lng in sorted(unique)]
        failures = {status for status, _ in observations if status != 'unique'}
        if failures:
            status = next(s for s in ('conflict', 'boundary', 'road', 'ambiguous', 'outside') if s in failures)
            return {**result, 'status': status, 'reason': 'not_all_address_points_resolve'}
        identifiers = {identifier for _, identifier in observations}
        if len(identifiers) != 1:
            return {**result, 'status': 'ambiguous', 'reason': 'address_points_in_different_parcels'}
        identifier = next(iter(identifiers))
        representative = self.representative_point(identifier)
        if representative is None:
            return {**result, 'status': 'conflict', 'reason': 'no_verified_interior_point'}
        return {**result, 'status': 'unique', 'cadastral_id': identifier, 'representative_point': representative, 'properties': self.properties(identifier), 'method': 'all_official_address_points_strict_native_and_display_containment'}


def build_index(cadastre_manifest_path, archives):
    """Validate the complete 24-archive capture, then build one offline index."""
    import shapefile
    from shapely.geometry import box, shape
    from shapely.errors import GEOSException
    from pyproj.exceptions import ProjError
    manifest_path, archives = Path(cadastre_manifest_path), Path(archives)
    manifest = read_json(manifest_path)
    if manifest.get('version') not in (1, 2) or manifest.get('completion', {}).get('status') != 'complete' or manifest['completion'].get('district_count') != 24 or len(manifest.get('sources', [])) != 24:
        raise ValueError('A complete verified 24-district cadastral capture is required')
    excluded = set(manifest.get('ambiguous_ids', []))
    if len(excluded) > 5000 or any(not isinstance(x, str) or CADASTRAL_ID.fullmatch(x) is None for x in excluded):
        raise ValueError('Invalid excluded cadastral identifiers')
    observations, sources, counts, seen_urls = [], [], Counter(), set()
    for index, source in enumerate(manifest['sources']):
        code = f'sofia-district-{index:02d}'
        url = official_download_url(source.get('source_url'))
        if source.get('code') != code or url in seen_urls or not timestamp_valid(source.get('captured_at')):
            raise ValueError('Repeated or invalid official capture provenance')
        seen_urls.add(url)
        archive_path = archives / (code + '.zip')
        if archive_path.is_symlink() or not archive_path.is_file() or archive_path.stat().st_size != source.get('zip_bytes') or file_digest(archive_path) != source.get('zip_sha256'):
            raise ValueError('Cadastral archive differs from its verified capture')
        label = source.get('label_bg', '')
        if not label.startswith('гр. София (68134) - район '):
            raise ValueError('Unexpected official district')
        rows = 0
        with ZipFile(archive_path) as archive:
            entries = archive.infolist()
            shapes = [entry for entry in entries if entry.filename.lower().endswith('.shp')]
            if len(shapes) != 1:
                raise ValueError('One official SHP is required')
            shp = shapes[0]
            stem, lookup = shp.filename[:-4], {entry.filename: entry for entry in entries}
            if any(stem + suffix not in lookup for suffix in ('.shx', '.prj', '.dbf', '.cpg')) or shp.file_size > 256 * 1024 * 1024 or lookup[stem + '.shx'].file_size > 8 * 1024 * 1024 or lookup[stem + '.prj'].file_size > 8192:
                raise ValueError('Invalid official geometry companion layout')
            transformer = projection(archive.read(stem + '.prj').decode('utf-8'))
            with archive.open(shp) as shp_file, archive.open(stem + '.shx') as shx_file:
                reader = shapefile.Reader(shp=shp_file, shx=shx_file)
                for (identifier, _, record), geometry in zip(archive_records(archive_path, label.split(' - ', 1)[1]), reader.iterShapes(), strict=True):
                    rows += 1
                    counts['records'] += 1
                    if counts['records'] > MAX_PARCELS:
                        raise ValueError('Parcel processing limit exceeded')
                    display = None
                    properties = {k: record.get(k) for k in ('use_code', 'use', 'purpose_code', 'purpose', 'district_name')}
                    counts['observed_transport_records'] += int(non_address_use(properties) == 'road')
                    try:
                        if geometry.shapeType != shapefile.POLYGON or not 4 <= len(geometry.points) <= MAX_FEATURE_VERTICES:
                            raise ValueError('Unsupported official polygon')
                        original = geometry.__geo_interface__
                        native = shape(original)
                        transformed = transform_geometry(original, transformer)
                        vertices, _ = geometry_vertices(transformed)
                        counts['vertices'] += vertices
                        if counts['vertices'] > MAX_VERTICES:
                            raise RuntimeError('Vertex processing limit exceeded')
                        display = shape(transformed)
                        if native.is_empty or not native.is_valid or display.is_empty or not display.is_valid or len(json_bytes(transformed)) > MAX_FEATURE_BYTES:
                            raise ValueError('Invalid or oversized official geometry')
                        identity = hashlib.sha256(native.normalize().wkb + b'\0' + json_bytes(record)).hexdigest()
                        observations.append(Parcel(identifier, native, display, transformer, properties, identity))
                    except (ValueError, TypeError, IndexError, OverflowError, GEOSException, ProjError):
                        counts['invalid_geometry_records'] += 1
                        excluded.add(identifier)
                        # A blocking envelope may reject a candidate but can
                        # never create an association or become public geometry.
                        if display is not None and not display.is_empty and all(math.isfinite(v) for v in display.bounds):
                            envelope = box(*display.bounds)
                            if not envelope.is_empty and envelope.is_valid:
                                observations.append(Parcel(identifier, None, envelope, None, properties, blocker=True))
                reader.close()
        if rows != source.get('record_count'):
            raise ValueError('Official SHP/DBF record count differs from capture')
        sources.append({k: source[k] for k in ('code', 'source_url', 'zip_sha256', 'captured_at')})
    if counts['records'] != manifest.get('source_record_total'):
        raise ValueError('Official source total does not reconcile')
    provenance = {'manifest_sha256': file_digest(manifest_path), 'snapshot_id': manifest['snapshot_id'], 'sources': sources, 'crs': 'EPSG:4326', 'native_crs': 'EPSG:7801', 'method': 'strict_native_and_published_display_containment'}
    return ParcelLinker(observations, excluded, provenance, counts)
