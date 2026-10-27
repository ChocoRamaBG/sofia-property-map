"""Strict containment regression fixtures; no network or account access."""
import math
import unittest

from business_parcel_linker import Parcel, ParcelLinker, TRANSPORT_USES

try:
    from shapely.geometry import Polygon, box
except ImportError:
    Polygon = box = None


@unittest.skipIf(Polygon is None, 'Install requirements-boundaries.txt for geometry tests')
class ParcelContainmentTests(unittest.TestCase):
    def parcel(self, number=1, geometry=None, properties=None, **kwargs):
        geometry = geometry if geometry is not None else box(23, 42, 24, 43)
        return Parcel(f'68134.1.{number}', geometry, geometry, properties=properties or {'use_code': '1000', 'use': 'Жилищно застрояване'}, **kwargs)

    def point(self, x=23.5, y=42.5, reference='address-1'):
        return {'lat': y, 'lng': x, 'reference_id': reference}

    def test_unique_returns_verified_interior_and_references(self):
        linker = ParcelLinker([self.parcel()])
        result = linker.resolve([self.point()])
        self.assertEqual((result['status'], result['cadastral_id']), ('unique', '68134.1.1'))
        self.assertEqual(result['reference_ids'], ['address-1'])
        self.assertIsNotNone(result['representative_point'])

    def test_hole_is_outside_and_hole_edge_is_boundary(self):
        shell = [(23, 42), (24, 42), (24, 43), (23, 43)]
        hole = [(23.4, 42.4), (23.6, 42.4), (23.6, 42.6), (23.4, 42.6)]
        linker = ParcelLinker([self.parcel(geometry=Polygon(shell, [hole]))])
        self.assertEqual(linker.resolve([self.point()])['status'], 'outside')
        self.assertEqual(linker.resolve([self.point(23.4, 42.5)])['status'], 'boundary')

    def test_outer_boundary_rejected(self):
        self.assertEqual(ParcelLinker([self.parcel()]).resolve([self.point(23, 42.5)])['status'], 'boundary')

    def test_coincident_distinct_parcels_ambiguous(self):
        self.assertEqual(ParcelLinker([self.parcel(1), self.parcel(2)]).resolve([self.point()])['status'], 'ambiguous')

    def test_identical_duplicate_id_collapses(self):
        self.assertEqual(ParcelLinker([self.parcel(), self.parcel()]).resolve([self.point()])['status'], 'unique')

    def test_conflicting_duplicate_id_blocks_both_shapes(self):
        linker = ParcelLinker([self.parcel(), self.parcel(geometry=box(24, 42, 25, 43))])
        self.assertEqual(linker.resolve([self.point()])['status'], 'conflict')
        self.assertEqual(linker.resolve([self.point(24.5)])['status'], 'conflict')

    def test_excluded_id_blocks_other_overlapping_parcel(self):
        linker = ParcelLinker([self.parcel(1), self.parcel(2)], excluded_ids=['68134.1.1'])
        self.assertEqual(linker.resolve([self.point()])['status'], 'conflict')

    def test_multiple_entrances_same_parcel_accepts_all(self):
        result = ParcelLinker([self.parcel()]).resolve([self.point(23.2, reference='a'), self.point(23.7, reference='b')])
        self.assertEqual(result['status'], 'unique')
        self.assertEqual(result['reference_ids'], ['a', 'b'])
        self.assertEqual(result['point_count'], 2)

    def test_entrances_in_different_parcels_rejected(self):
        linker = ParcelLinker([self.parcel(), self.parcel(2, box(24, 42, 25, 43))])
        result = linker.resolve([self.point(reference='a'), self.point(24.5, reference='b')])
        self.assertEqual(result['status'], 'ambiguous')
        self.assertIsNone(result['cadastral_id'])

    def test_one_outside_point_cannot_be_dropped(self):
        result = ParcelLinker([self.parcel()]).resolve([self.point(reference='a'), self.point(25, reference='b')])
        self.assertEqual(result['status'], 'outside')
        self.assertIsNone(result['cadastral_id'])

    def test_duplicate_coordinates_keep_all_reference_ids(self):
        result = ParcelLinker([self.parcel()]).resolve([self.point(reference='a'), self.point(reference='b')])
        self.assertEqual((result['status'], result['point_count']), ('unique', 1))
        self.assertEqual(result['reference_ids'], ['a', 'b'])

    def test_transport_parcel_rejected(self):
        for code, label in TRANSPORT_USES.items():
            linker = ParcelLinker([self.parcel(properties={'use_code': code, 'use': label})])
            self.assertEqual(linker.resolve([self.point()])['status'], 'road')
            self.assertIsNone(linker.representative_point('68134.1.1'))

    def test_mismatched_known_transport_code_requires_review(self):
        linker = ParcelLinker([self.parcel(properties={'use_code': '2110', 'use': 'Unexpected changed classification'})])
        self.assertEqual(linker.resolve([self.point()])['status'], 'conflict')

    def test_repair_workshop_not_a_road(self):
        linker = ParcelLinker([self.parcel(properties={'use_code': '2280', 'use': 'За ремонт и поддържане на транспортни средства'})])
        self.assertEqual(linker.resolve([self.point()])['status'], 'unique')

    def test_new_road_label_is_held_for_review(self):
        linker = ParcelLinker([self.parcel(properties={'use_code': '9999', 'use': 'За автомагистрала'})])
        self.assertEqual(linker.resolve([self.point()])['status'], 'conflict')

    def test_invalid_point_does_not_resolve_from_remaining(self):
        linker = ParcelLinker([self.parcel()])
        for bad in [self.point(math.nan), self.point(math.inf), {'lat': 42.5, 'lng': 23.5, 'reference_id': 'unsafe contact@example.com'}, {'lat': True, 'lng': 23.5, 'reference_id': 'a'}]:
            self.assertEqual(linker.resolve([self.point(), bad])['status'], 'conflict')

    def test_strict_native_and_display_containment(self):
        parcel = self.parcel(geometry=box(23, 42, 24, 43))
        parcel.native = box(23, 42, 23.4, 43)
        self.assertEqual(ParcelLinker([parcel]).resolve([self.point()])['status'], 'boundary')

    def test_empty_points_and_over_limit(self):
        linker = ParcelLinker([self.parcel()])
        self.assertEqual(linker.resolve([])['status'], 'outside')
        self.assertEqual(linker.resolve([self.point()] * 1025)['status'], 'conflict')


if __name__ == '__main__':
    unittest.main()
