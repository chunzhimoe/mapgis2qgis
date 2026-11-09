"""Optional PyQGIS smoke: custom projection PRJs from the native writer open correctly."""
import json
from pathlib import Path
import sys
import tempfile

import native_fixtures as F
from test_georef_projections import conic_header
from mapgis_annotations import export_native
from pyproj import CRS, Proj
from qgis.core import QgsApplication, QgsVectorLayer


def main():
    app = QgsApplication([], False)
    app.initQgis()
    checked = []
    try:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            F.write_points(source / 'geographic.WT', [{'x': 105, 'y': 30, 'text': '矿点'}],
                           proj=0, ellipsoid=7, scale=0)
            for number, method in ((2, 'aea'), (3, 'lcc')):
                t = Proj('+proj=%s +lon_0=105 +lat_0=30 +lat_1=25 +lat_2=47 '
                         '+x_0=123456 +y_0=654321 +datum=WGS84' % method)
                x, y = t(106, 31)
                path = source / (method + '.WT')
                F.write_points(path, [{'x': x / 50, 'y': y / 50, 'text': 'T#-2'}],
                               proj=number, ellipsoid=7, scale=50000, cm=105)
                conic_header(path)
            manifest = export_native(source, root / 'output')
            for name, entry in manifest['layers'].items():
                layer = QgsVectorLayer(str(root / 'output' / (name + '.shp')), name, 'ogr')
                assert layer.isValid() and layer.crs().isValid(), name
                assert layer.featureCount() == 1, name
                actual = CRS(layer.crs().toWkt())
                assert actual.equals(CRS(entry['crs_wkt']), ignore_axis_order=True), name
                checked.append(name)
                del layer
    finally:
        app.exitQgis()
    result = {'status': 'PASS', 'valid_qgis_layers': checked}
    Path(sys.argv[1]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
