import unittest
from shapely.geometry import Polygon
from mapgis_annotations import AnnotationError, AnnotationPoint as P, PairingConfig, pair_annotations, crosswalk


class PairTests(unittest.TestCase):
    def config(self, **values):
        return PairingConfig(min_dx=1, max_dx=20, max_dy=2, require_legend=False, **values)

    def test_custom_ascii_symbols_and_legend(self):
        points = [P(10, 0, 0, 'ROCK'), P(20, 10, 0, 'AGE'), P(30, 200, 200, 'untouched')]
        cfg = self.config(rock_pattern='ROCK', age_pattern='AGE')
        cfg.require_legend = True
        result = pair_annotations(points, 'EPSG:32648', cfg, {('ROCK', 'AGE')})
        self.assertEqual(result['display'][10], 'ROCKAGE')
        self.assertEqual(result['display'][20], '')
        self.assertEqual(result['display'][30], 'untouched')
        result = pair_annotations(points, 'EPSG:32648', cfg, set())
        self.assertEqual(result['unresolved'][0]['reason'], 'NOT_IN_LEGEND')

    def test_degree_coordinates_refused_and_explicit_projection_allowed(self):
        points = [P(0, 105, 30, 'γ'), P(1, 105.0001, 30, 'T#-2')]
        with self.assertRaisesRegex(AnnotationError, 'degree'):
            pair_annotations(points, 'EPSG:4326', self.config())
        cfg = self.config(working_crs='EPSG:32648')
        self.assertEqual(len(pair_annotations(points, 'EPSG:4326', cfg)['pairs']), 1)

    def test_reverse_ambiguity_counts_all_edges(self):
        points = [P(0, 0, 0, 'γ'), P(1, 15, 0, 'δ'),
                  P(2, 10, 0, 'T#-2'), P(3, 20, 0, 'T#-3')]
        result = pair_annotations(points, 'EPSG:32648', self.config())
        self.assertFalse(result['pairs'])
        self.assertIn('REVERSE_AMBIGUITY', {r['reason'] for r in result['unresolved']})

    def test_duplicate_ids_and_invalid_thresholds(self):
        with self.assertRaises(AnnotationError):
            pair_annotations([P(1, 0, 0, 'γ'), P(1, 10, 0, 'T#-2')], 'EPSG:32648', self.config())
        with self.assertRaises(AnnotationError):
            pair_annotations([], 'EPSG:32648', PairingConfig(max_dx=float('nan')))

    def test_projected_feet_are_converted_to_metres(self):
        # EPSG:2277 uses US survey feet, not metres; ten feet is ~3.048 m.
        points = [P(0, 3000000, 10000000, 'γ'), P(1, 3000010, 10000000, 'T#-2')]
        result = pair_annotations(points, 'EPSG:2277', self.config())
        self.assertAlmostEqual(result['pairs'][0]['dx_m'], 3.048006096, places=6)

    def test_invalid_regex_is_an_actionable_error(self):
        with self.assertRaisesRegex(AnnotationError, 'regular expression'):
            pair_annotations([], 'EPSG:32648', self.config(rock_pattern='['))


class CrosswalkTests(unittest.TestCase):
    def test_boundaries_and_outside_are_preserved(self):
        polygons = [(42, Polygon([(0,0),(1,0),(1,1),(0,1)])),
                    (99, Polygon([(1,0),(2,0),(2,1),(1,1)]))]
        result = crosswalk([P(5, 1, .5, 'x'), P(8, 8, 8, 'y')], polygons, 'EPSG:4326', 'EPSG:4326')
        self.assertEqual(len(result['rows']), 3)
        self.assertEqual(result['rows'][0]['match_count'], 2)
        self.assertEqual(result['rows'][-1]['status'], 'UNMATCHED')

    def test_invalid_polygon_policy_and_different_crs(self):
        invalid = Polygon([(0,0),(2,2),(0,2),(2,0)])
        result = crosswalk([P(2, 1, 1, 'x')], [(3, invalid)], 'EPSG:4326', 'EPSG:4326')
        self.assertEqual(result['invalid_polygon_fids'], [3])
        self.assertEqual(result['rows'][0]['status'], 'UNMATCHED')
        with self.assertRaises(AnnotationError):
            crosswalk([], [(3, invalid)], 'EPSG:4326', 'EPSG:4326', invalid_policy='error')
        square = Polygon([(0,0),(200000,0),(200000,200000),(0,200000)])
        result = crosswalk([P(2, 1, 1, 'x')], [(4, square)], 'EPSG:4326', 'EPSG:3857')
        self.assertEqual(result['rows'][0]['polygon_fid'], 4)


if __name__ == '__main__':
    unittest.main()
