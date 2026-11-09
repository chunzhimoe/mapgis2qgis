from pathlib import Path
import json
import tempfile
import unittest

import shapefile

import native_fixtures as F
from mapgis_annotations import (AnnotationError, NativeFormatError, export_native, read_mpj_paths,
                                read_native_layer, run_workflow)
from mapgis_annotations.mapgis_native import (NativeField, _area2, convert_native_file, organize_rings,
                                              write_shapefile)

try:
    import pyproj
except ImportError:
    pyproj = None

STR, INT, DBL = 0, 3, 5


class NativeReading(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_points_live_only_with_attributes_and_symbols(self):
        path = self.root / 'labels.WT'
        F.write_points(path, [
            {'x': 1, 'y': 2, 'text': 'ηγT#-2'},
            {'x': 3, 'y': 4, 'text': 'deleted', 'alive': False},
            {'x': 5, 'y': 6, 'type': 1, 'subgraph': 42, 'color': 7}],
            fields=[('ID', INT, 4, 8, 0), ('名称', STR, 21, 20, 0)],
            records=[[10, '甲'], [11, '乙'], [12, '丙']])
        layer = read_native_layer(path)
        self.assertEqual(layer.kind, 'POINT')
        self.assertEqual([f.name for f in layer.fields], ['ID', '名称', '点类型', '注记', '子图号', '颜色'])
        self.assertEqual(layer.features, [((1.0, 2.0), [10, '甲', '注释', 'ηγT#-2', None, 0]),
                                          ((5.0, 6.0), [12, '丙', '子图', None, 42, 7])])
        self.assertEqual(read_native_layer(path, style=False).features[1][1], [12, '丙'])

    def test_lines_and_missing_attribute_table(self):
        path = self.root / 'faults.WL'
        F.write_lines(path, [([(0, 0), (1, 1), (2, 0)], True), ([(9, 9), (8, 8)], False)])
        layer = read_native_layer(path)
        self.assertEqual([f.name for f in layer.fields], ['ID', '线型', '线颜色', '线宽'])
        self.assertEqual(layer.features, [([(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)], [None, 3, 5, 0.25])])

    def test_regions_arc_lists_holes_degenerate_and_duplicates(self):
        outer = [(0, 0), (0, 10), (10, 10)]
        outer2 = [(10, 10), (10, 0), (0, 0)]
        hole = [(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)]
        spike = [(20, 20), (21, 21)]
        path = self.root / 'geology.WP'
        F.write_regions(path, [(outer, True), (outer2, True), (hole, True), (spike, True)],
                        [([1, 2, 0, 3, 0, 3], True, 4), ([4], True, 5), ([1, 2], False, 6)],
                        fields=[('ID', INT, 4, 8, 0), ('面积', DBL, 8, 15, 6)],
                        records=[[1, 96.0], [2, 0.0], [3, 1.0]])
        layer = read_native_layer(path)
        self.assertEqual(len(layer.features), 2)
        rings = layer.features[0][0]
        self.assertEqual(len(rings), 3)                              # MapGIS order, duplicate kept here
        self.assertEqual(rings[0], [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0), (0.0, 0.0)])
        nested = organize_rings(rings)
        self.assertEqual(len(nested), 2)                             # duplicate hole dropped
        self.assertLess(_area2(nested[0]), 0)                        # outer clockwise
        self.assertGreater(_area2(nested[1]), 0)                     # hole counter-clockwise
        self.assertEqual(layer.features[1][0], [[(20.0, 20.0), (21.0, 21.0), (20.0, 20.0)]])  # kept like MapGIS
        self.assertEqual(layer.features[0][1], [1, 96.0, 4, 7])

    def test_rejects_non_mapgis_and_truncated_files(self):
        bad = self.root / 'x.WT'
        bad.write_bytes(b'\xff' * 500)
        with self.assertRaises(NativeFormatError):
            read_native_layer(bad)
        good = self.root / 'y.WT'
        F.write_points(good, [{'x': 1, 'y': 1, 'text': 'a'}])
        bad.write_bytes(good.read_bytes()[:530])
        with self.assertRaises(NativeFormatError):
            read_native_layer(bad)

    def test_project_paths(self):
        F.write_points(self.root / 'a.WT', [{'x': 1, 'y': 1, 'text': 'a'}])
        F.write_project(self.root / 'map.MPJ', ['.\\a.WT', '..\\base\\b.WL'])
        paths = read_mpj_paths(self.root / 'map.MPJ')
        self.assertEqual([p.name for p in paths], ['a.WT', 'b.WL'])
        self.assertTrue(paths[0].is_file())
        self.assertFalse(paths[1].exists())


class ShapefileWriting(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_dbf_formatting_matches_mapgis_and_never_truncates(self):
        base = self.root / 'fmt'
        fields = [NativeField('长度', 'N', 15, 6), NativeField('D', 'N', 10, 2), NativeField('DIP', 'N', 2, 0),
                  NativeField('名称', 'C', 6)]
        written = write_shapefile(base, 'POINT', fields,
                                  [((1.0, 2.0), [0.0078125, 1111.885, 220, '五龙沟金矿']),
                                   ((3.0, 4.0), [None, 1241.495, None, None])])
        self.assertEqual(written[2].width, 3)                        # widened instead of "22"
        with shapefile.Reader(str(base) + '.shp', encoding='gbk') as reader:
            rows = [list(r) for r in reader.records()]
            self.assertEqual(reader.shapeType, shapefile.POINT)
        self.assertEqual(rows[0][:3], [0.007813, 1111.89, 220])     # MS CRT rounding
        self.assertEqual(rows[0][3], '五龙沟')                       # cut on a character boundary
        self.assertEqual(rows[1][1], 1241.49)
        self.assertIsNone(rows[1][0])
        self.assertEqual((self.root / 'fmt.cpg').read_text(), 'GBK')

    def test_polygon_and_line_geometry_roundtrip(self):
        path = self.root / 'r.WP'
        F.write_regions(path, [([(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)], True),
                               ([(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)], True)],
                        [([1, 0, 2], True, 1)])
        report = convert_native_file(path, self.root / 'out_r', factor=2.0)
        self.assertEqual(report['features'], 1)
        with shapefile.Reader(str(self.root / 'out_r.shp')) as reader:
            shape = reader.shape(0)
            self.assertEqual(reader.shapeType, shapefile.POLYGON)
            self.assertEqual(list(shape.parts), [0, 5])
            self.assertEqual(list(shape.bbox), [0.0, 0.0, 20.0, 20.0])
            self.assertEqual(list(shape.points[0]), [0.0, 0.0])
            self.assertEqual(list(shape.points[1]), [0.0, 20.0])    # clockwise outer


@unittest.skipIf(pyproj is None, 'pyproj (spatial extra) not installed')
class NativeExport(unittest.TestCase):
    """A synthetic 1:250 000 Beijing 1954 GK CM105E map, stored in paper millimetres."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.src = self.root / 'map'
        self.src.mkdir()
        t = pyproj.Transformer.from_crs(4214, 21458, always_xy=True)
        self.sites = [(104.5 + 0.01 * i, 34.2 + 0.005 * i) for i in range(6)]
        mm = [(x / 250.0, y / 250.0) for x, y in (t.transform(lo, la) for lo, la in self.sites)]
        dms = [('%03d%02d%02d' % _dms(lo), '%02d%02d%02d' % _dms(la)) for lo, la in self.sites]
        F.write_points(self.src / 'SITES.WT', [{'x': x, 'y': y, 'text': '矿点%d' % i} for i, (x, y) in enumerate(mm)],
                       fields=[('ID', INT, 4, 8, 0), ('CODEA', STR, 11, 10, 0), ('CODEB', STR, 11, 10, 0)],
                       records=[[i, a, b] for i, (a, b) in enumerate(dms)])
        ring = [mm[0], (mm[0][0], mm[5][1]), mm[5], (mm[5][0], mm[0][1]), mm[0]]
        F.write_regions(self.src / 'GEOL.WP', [(ring, True)], [([1], True, 3)],
                        fields=[('ID', INT, 4, 8, 0), ('面积', DBL, 8, 15, 6)], records=[[1, 5.0]])
        F.write_lines(self.src / 'BLANK.WL', [([mm[1], mm[2]], True)], proj=0, ellipsoid=0, scale=0.0, cm=None)
        F.write_lines(self.src / 'TENK.WL', [([(x * 25, y * 25) for x, y in mm[1:4]], True)],
                      proj=0, ellipsoid=0, scale=0.0, cm=None)              # stored at 1:10 000
        F.write_points(self.src / 'INSET.WT', [{'x': 3, 'y': 4, 'text': '位置图'}], proj=0, ellipsoid=0,
                       scale=0.0, cm=None)

    def tearDown(self):
        self.temp.cleanup()

    def test_frames_decisions_evidence_and_protection(self):
        before = {p.name: p.read_bytes() for p in self.src.iterdir()}
        manifest = export_native(self.src, self.root / 'out')
        self.assertEqual({p.name: p.read_bytes() for p in self.src.iterdir()}, before)
        layers = manifest['layers']
        self.assertEqual(manifest['map_frame']['epsg'], 21458)
        self.assertEqual(layers['SITES_点']['decision'], 'header frame')
        self.assertEqual(layers['SITES_点']['factor'], 250.0)
        self.assertEqual(layers['SITES_点']['lonlat_attribute_check']['fields'], ['CODEA', 'CODEB'])
        self.assertLess(layers['SITES_点']['lonlat_attribute_check']['median_m'], 60)  # 1" rounding
        self.assertTrue(layers['BLANK_线']['decision'].startswith('inside map frame'))
        self.assertEqual(layers['BLANK_线']['epsg'], 21458)
        self.assertIn('INFERRED', layers['TENK_线']['decision'])
        self.assertEqual(layers['TENK_线']['factor'], 10.0)
        self.assertIsNone(layers['INSET_点']['epsg'])
        self.assertEqual(manifest['summary']['without_crs'], ['INSET_点'])
        out = self.root / 'out'
        self.assertTrue((out / 'SITES_点.prj').read_text().startswith('PROJCS["Beijing_1954'))
        self.assertFalse((out / 'INSET_点.prj').exists())
        with shapefile.Reader(str(out / 'GEOL_区.shp'), encoding='gbk') as reader:
            area = reader.record(0)['面积']
        self.assertAlmostEqual(area, 5.0 * 250 ** 2)
        with shapefile.Reader(str(out / 'SITES_点.shp'), encoding='gbk') as reader:
            x, y = reader.shape(0).points[0]
        lon, lat = pyproj.Transformer.from_crs(21458, 4214, always_xy=True).transform(x, y)
        self.assertAlmostEqual(lon, self.sites[0][0], 6)
        self.assertAlmostEqual(lat, self.sites[0][1], 6)
        self.assertTrue(json.loads((out / 'native_export.json').read_text(encoding='utf-8'))['source_sha256'])
        with self.assertRaises(AnnotationError):
            export_native(self.src, self.root / 'out')                  # existing output
        with self.assertRaises(AnnotationError):
            export_native(self.src, self.src / 'nested')                # inside the input tree

    def test_overrides_and_stored_units(self):
        manifest = export_native(self.src, self.root / 'stored', georeference=False)
        self.assertEqual(manifest['summary']['with_crs'], 0)
        self.assertTrue(all(e['factor'] == 1.0 for e in manifest['layers'].values()))
        given = export_native(self.src, self.root / 'given', epsg=2432)
        self.assertEqual(given['map_frame']['epsg'], 2432)
        self.assertIn('(given)', given['layers']['SITES_点']['crs'])

    def test_output_feeds_annotation_workflow(self):
        export_native(self.src, self.root / 'shp')
        result = run_workflow(self.root / 'shp', self.root / 'dataset', {'annotation_layers': ['SITES_点']})
        self.assertEqual(result['converted_records'], 6)
        self.assertEqual(result['layers']['SITES_点']['conversion']['note_field'], '注记')

    def test_unrelated_nonstandard_gk_header_does_not_gain_custom_crs(self):
        # A stale Xian80/CM48 header can invert to plausible coordinates near
        # 51E, but it must retain 0.2.0's unassigned status on this China GK map.
        project = pyproj.Proj('+proj=tmerc +lon_0=48 +x_0=500000 +a=6378140 +b=6356755.288157528')
        x, y = project(50.95, 37.13)
        F.write_points(self.src / 'RECTFRAM.WT', [{'x': x / 2, 'y': y / 2, 'text': '旧图框'}],
                       proj=5, ellipsoid=2, scale=2000, cm=48)
        manifest = export_native(self.src, self.root / 'out')
        e = manifest['layers']['RECTFRAM_点']
        self.assertIsNone(e['crs_wkt'])
        self.assertEqual(e['factor'], 1)
        self.assertFalse((self.root / 'out/RECTFRAM_点.prj').exists())


def _dms(deg):
    d = int(deg)
    m = int((deg - d) * 60)
    s = int(round(((deg - d) * 60 - m) * 60))
    if s == 60:
        m, s = m + 1, 0
    return d, m, s


if __name__ == '__main__':
    unittest.main()
