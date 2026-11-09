"""Export native synthetic control maps and independently re-open their SHP/PRJ."""
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import shapefile
import native_fixtures as F
from mapgis_annotations import AnnotationError, export_native, read_native_layer, run_workflow
from mapgis_annotations.cli import main

try:
    import pyproj
except ImportError:
    pyproj = None


def conic_header(path, lat0=300000, lat1=250000, lat2=470000, x0=123456, y0=654321):
    raw = bytearray(path.read_bytes())
    for offset, value in zip((175, 183, 191, 199, 207), (lat0, lat1, lat2, x0, y0)):
        struct.pack_into('<d', raw, offset, value)
    path.write_bytes(raw)


@unittest.skipIf(pyproj is None, 'pyproj not installed')
class ProjectionExport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.src = self.root / 'source'
        self.src.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_geographic_zero_nan_scale_and_metre_residual(self):
        sites = [(-105.25 + i * 0.01, -30.5 + i * 0.005) for i in range(4)]
        for number, scale in enumerate((0, float('nan'))):
            path = self.src / ('sites%d.WT' % number)
            F.write_points(path, [{'x': x, 'y': y, 'text': 'T#-2'} for x, y in sites], proj=0,
                           ellipsoid=7, scale=scale, cm=None,
                           fields=[('longitude', 5, 8, 18, 7), ('latitude', 5, 8, 18, 7)],
                           records=[[x + 0.001, y] for x, y in sites])
        # A nearby paper-space inset must not inherit a geographic frame.
        F.write_points(self.src / 'inset.WT', [{'x': -105.24, 'y': -30.49, 'text': '位置图'}],
                       proj=0, ellipsoid=0, scale=0, cm=None)
        manifest = export_native(self.src, self.root / 'out')
        self.assertEqual(manifest['summary']['with_crs'], 2)
        self.assertEqual(manifest['summary']['without_crs'], ['inset_点'])
        for number in range(2):
            e = manifest['layers']['sites%d_点' % number]
            self.assertEqual((e['epsg'], e['factor']), (4326, 1.0))
            check = e['lonlat_attribute_check']
            self.assertEqual(check['metric'], 'geodesic')
            self.assertGreater(check['median_m'], 90)  # .001 degrees is ~96m here, not .001m
            self.assertLess(check['median_m'], 100)
            base = self.root / 'out' / ('sites%d_点' % number)
            self.assertEqual(pyproj.CRS(base.with_suffix('.prj').read_text()).to_epsg(), 4326)
            with shapefile.Reader(str(base), encoding='gbk') as reader:
                self.assertEqual(list(reader.shape(0).points[0]), list(sites[0]))
        # Nonfinite header scale is audited as null, never JSON NaN.
        text = (self.root / 'out/native_export.json').read_text(encoding='utf-8')
        self.assertNotIn('NaN', text)
        result = run_workflow(self.root / 'out', self.root / 'notes', {'annotation_layers': ['sites0_点']})
        self.assertEqual(result['converted_records'], 4)

    def test_albers_lambert_custom_wkt_units_and_feature_types(self):
        for number, (projection, method) in enumerate(((2, 'aea'), (3, 'lcc'))):
            transform = pyproj.Proj('+proj=%s +lon_0=105 +lat_0=30 +lat_1=25 +lat_2=47 '
                                     '+x_0=123456 +y_0=654321 +datum=WGS84' % method)
            controls = [transform(105, 30), transform(106, 31), transform(107, 32)]
            stored = [(x / 50, y / 50) for x, y in controls]
            path = self.src / ('projection%d.WT' % number)
            F.write_points(path, [{'x': x, 'y': y, 'text': 'ηγT#-2'} for x, y in stored],
                           proj=projection, ellipsoid=7, scale=50000, cm=105)
            conic_header(path)
            line = self.src / ('projection%d.WL' % number)
            F.write_lines(line, [(stored, True)], proj=projection, ellipsoid=7, scale=50000, cm=105)
            conic_header(line)
            ring = [stored[0], (stored[0][0], stored[2][1]), stored[2],
                    (stored[2][0], stored[0][1]), stored[0]]
            area = self.src / ('projection%d.WP' % number)
            F.write_regions(area, [(ring, True)], [([1], True, 3)], proj=projection,
                            ellipsoid=7, scale=50000, cm=105,
                            fields=[('面积', 5, 8, 15, 6)], records=[[4.0]])
            conic_header(area)
        before = {p.name: p.read_bytes() for p in self.src.iterdir()}
        manifest = export_native(self.src, self.root / 'out')
        self.assertEqual(manifest['summary']['with_crs'], 6)
        for number, method in enumerate(('Albers', 'Lambert')):
            for kind in ('点', '线', '区'):
                name = 'projection%d_%s' % (number, kind)
                e = manifest['layers'][name]
                self.assertEqual(e['factor'], 50)
                self.assertIsNone(e['epsg'])  # a valid custom CRS need not have an EPSG code
                self.assertTrue(e['lonlat_window']['ok'])
                crs = pyproj.CRS((self.root / 'out' / (name + '.prj')).read_text())
                self.assertIn(method, crs.coordinate_operation.method_name)
                with shapefile.Reader(str(self.root / 'out' / (name + '.shp')), encoding='gbk') as reader:
                    x, y = reader.shape(0).points[0]
                    lon, lat = pyproj.Transformer.from_crs(crs, 4326, always_xy=True).transform(x, y)
                    self.assertAlmostEqual(lon, 105, places=7)
                    self.assertAlmostEqual(lat, 30, places=7)
                    if kind == '区':
                        self.assertEqual(reader.record(0)['面积'], 4 * 50 ** 2)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.src.iterdir()})

    def test_wgs84_tm_southern_control_and_fractional_western_meridian(self):
        cm = -(105 + 30 / 60 + 15.5 / 3600)
        project = pyproj.Proj('+proj=tmerc +lon_0=%s +lat_0=0 +k=1 +x_0=500000 +datum=WGS84' % cm)
        x, y = project(cm + 0.25, -30)
        path = self.src / 'western.WT'
        F.write_points(path, [{'x': x / 10, 'y': y / 10, 'text': 'a'}], proj=5, ellipsoid=7, scale=10000)
        raw = bytearray(path.read_bytes())
        struct.pack_into('<d', raw, 151, -1053015.5)
        path.write_bytes(raw)
        self.assertAlmostEqual(read_native_layer(path).header_cm, cm)
        e = export_native(self.src, self.root / 'out')['layers']['western_点']
        self.assertTrue(e['crs_wkt'])
        self.assertEqual(e['factor'], 10)
        self.assertTrue(e['lonlat_window']['ok'])

    def test_invalid_candidates_and_factor_are_audited_or_rejected(self):
        F.write_points(self.src / 'invalid.WT', [{'x': 300, 'y': 100, 'text': 'a'}],
                       proj=0, ellipsoid=7, scale=0)
        F.write_points(self.src / 'unknown.WT', [{'x': 105, 'y': 35, 'text': 'a'}],
                       proj=0, ellipsoid=255, scale=0)
        m = export_native(self.src, self.root / 'out')
        self.assertEqual(m['summary']['with_crs'], 0)
        self.assertIn('unknown ellipsoid', m['layers']['unknown_点']['header_candidate']['reason'])
        for factor in (0, -1, float('nan'), float('inf')):
            output = self.root / ('bad-%s' % factor)
            with self.assertRaises(AnnotationError):
                export_native(self.src, output, factor=factor)
            self.assertFalse(output.exists())

    def test_explicit_geographic_override_and_stored_units(self):
        F.write_points(self.src / 'unknown.WT', [{'x': 105, 'y': 35, 'text': 'a'}],
                       proj=0, ellipsoid=255, scale=0)
        given = export_native(self.src, self.root / 'given', epsg=4326)
        self.assertEqual(given['layers']['unknown_点']['epsg'], 4326)
        self.assertEqual(given['layers']['unknown_点']['factor'], 1)
        with self.assertRaises(AnnotationError):
            export_native(self.src, self.root / 'conflict', epsg=4326, factor=50)
        stored = export_native(self.src, self.root / 'stored', georeference=False)
        self.assertEqual(stored['summary']['with_crs'], 0)

    def test_geographic_factor_cannot_rescale_degrees(self):
        F.write_points(self.src / 'sites.WT', [{'x': 2, 'y': 1, 'text': 'a'}],
                       proj=0, ellipsoid=7, scale=0)
        with self.assertRaises(AnnotationError):
            export_native(self.src, self.root / 'bad', factor=50)
        self.assertFalse((self.root / 'bad').exists())
        given = export_native(self.src, self.root / 'explicit_projected', epsg=3857, factor=50)
        self.assertEqual(given['layers']['sites_点']['factor'], 50)
        self.assertEqual(given['layers']['sites_点']['epsg'], 3857)

    def test_negative_attribute_packed_and_separated_dms(self):
        for name, longitude in (('packed', '-1053015.5'), ('separated', '-105 30 15.5')):
            x, y = -(105 + 30 / 60 + 15.5 / 3600), -30.5
            F.write_points(self.src / (name + '.WT'), [{'x': x, 'y': y, 'text': 'a'}] * 3,
                           proj=0, ellipsoid=7, scale=0,
                           fields=[('longitude', 0, 24, 24, 0), ('latitude', 0, 24, 24, 0)],
                           records=[[longitude, '-30 30 0']] * 3)
        m = export_native(self.src, self.root / 'out')
        for e in m['layers'].values():
            self.assertEqual(e['lonlat_attribute_check']['median_m'], 0)

    def test_cli_runs_native_geographic_export(self):
        F.write_points(self.src / 'sites.WT', [{'x': 105, 'y': 35, 'text': 'a'}],
                       proj=0, ellipsoid=7, scale=0)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = main(['from-mapgis', str(self.src), str(self.root / 'cli')])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout.getvalue())['summary']['with_crs'], 1)
