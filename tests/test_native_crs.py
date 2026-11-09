"""Projection-control tests use known geographic positions, not parser internals."""
import struct
import unittest

from mapgis_annotations.native_crs import decode_dms, header_crs, read_header_parameters
from mapgis_annotations import NativeFormatError

try:
    import pyproj
except ImportError:
    pyproj = None


def header(projection=0, ellipsoid=7, scale=0, cm=1050000, lat0=0, lat1=250000,
           lat2=470000, x0=123456, y0=654321):
    raw = bytearray(340)
    raw[109], raw[110] = projection, ellipsoid
    for offset, value in zip((143, 151, 175, 183, 191, 199, 207), (scale, cm, lat0, lat1, lat2, x0, y0)):
        struct.pack_into('<d', raw, offset, value)
    return bytes(raw)


class HeaderParameters(unittest.TestCase):
    def test_signed_fractional_short_dms(self):
        self.assertAlmostEqual(decode_dms(-1053015.5), -(105 + 30 / 60 + 15.5 / 3600))
        self.assertAlmostEqual(decode_dms(30.5), 30.5 / 3600)
        self.assertEqual(decode_dms(0), 0)
        for value in (float('nan'), float('inf'), 1056060):
            self.assertIsNone(decode_dms(value))

    def test_offsets_truncation_and_nonfinite(self):
        p = read_header_parameters(header(projection=2, cm=-1053015.5, scale=float('nan')))
        self.assertAlmostEqual(p['central_meridian'], -(105 + 30 / 60 + 15.5 / 3600))
        self.assertEqual((p['false_easting'], p['false_northing']), (123456, 654321))
        self.assertIsNone(p['scale'])
        with self.assertRaises(NativeFormatError):
            read_header_parameters(b'\0' * 214)


@unittest.skipIf(pyproj is None, 'pyproj not installed')
class HeaderProjection(unittest.TestCase):
    def test_geographic_scale_zero_or_nan_never_changes_degrees(self):
        for scale in (0, float('nan'), -10):
            c = header_crs(read_header_parameters(header(scale=scale)))
            self.assertEqual(c.factor, 1)
            self.assertEqual(pyproj.CRS(c.wkt).to_epsg(), 4326)

    def test_conic_control_points_and_offsets(self):
        for projection, name in ((2, 'aea'), (3, 'lcc')):
            c = header_crs(read_header_parameters(header(projection=projection, scale=50000, lat0=300000)))
            self.assertEqual(c.factor, 50)
            crs = pyproj.CRS(c.wkt)
            t = pyproj.Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
            self.assertAlmostEqual(t.transform(105, 30)[0], 123456, places=5)
            self.assertAlmostEqual(t.transform(105, 30)[1], 654321, places=5)
            reference = pyproj.Proj('+proj=%s +lon_0=105 +lat_0=30 +lat_1=25 +lat_2=47 '
                                    '+x_0=123456 +y_0=654321 +datum=WGS84' % name)
            expected, actual = reference(108.25, 36.5), t.transform(108.25, 36.5)
            for a, b in zip(expected, actual):
                self.assertAlmostEqual(a, b, places=6)

    def test_tm_and_extra_ellipsoids_without_fixed_datum_shifts(self):
        for code in (1, 2, 7, 9, 10, 11, 16, 116):
            c = header_crs(read_header_parameters(header(projection=5, ellipsoid=code, scale=10000)))
            crs = pyproj.CRS(c.wkt)
            x, y = pyproj.Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True).transform(105, 0)
            self.assertAlmostEqual(x, 500000, places=6)
            self.assertAlmostEqual(y, 0, places=6)
            self.assertFalse(crs.is_bound)
            self.assertTrue(any('NO_REGIONAL_DATUM_SHIFT' in w for w in c.warnings))

    def test_unknown_or_corrupt_parameters_remain_unassigned(self):
        for kwargs in ({'ellipsoid': 255}, {'projection': 99}, {'projection': 5, 'scale': 0},
                       {'projection': 5, 'scale': float('inf')}, {'projection': 5, 'scale': 1000, 'cm': float('nan')},
                       {'projection': 2, 'scale': 1000, 'lat1': float('inf')},
                       {'projection': 3, 'scale': 1000, 'lat1': 0, 'lat2': 0}):
            with self.subTest(kwargs=kwargs):
                c = header_crs(read_header_parameters(header(**kwargs)))
                self.assertIsNone(c.wkt)
                self.assertEqual(c.factor, 1)
                self.assertTrue(c.reason)
