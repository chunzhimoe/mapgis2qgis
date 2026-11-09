"""Read back a native export, verify source/product hashes and write an inventory."""
import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path

import shapefile
from pyproj import CRS
from shapely.geometry import shape
from mapgis_annotations.shapefiles import sha256


def verify(dataset):
    manifest = json.loads((dataset / 'native_export.json').read_text(encoding='utf-8'))
    for source, expected in manifest['source_sha256'].items():
        assert sha256(source) == expected, source
    inventory, types = [], Counter()
    for name, item in manifest['layers'].items():
        for product, expected in item['products'].items():
            assert sha256(dataset / product) == expected, product
        base = dataset / name
        with shapefile.Reader(str(base.with_suffix('.shp')), encoding='gbk') as reader:
            assert len(reader) == item['features'], name
            rows, nulls, invalid = list(reader.records()), 0, 0
            assert len(rows) == item['features'], name
            for geometry in reader.shapes():
                if geometry.shapeType == shapefile.NULL:
                    nulls += 1
                    continue
                assert all(math.isfinite(c) for p in geometry.points for c in p), name
                if geometry.shapeType == shapefile.POLYGON:
                    invalid += not shape(geometry.__geo_interface__).is_valid
        crs_input = item.get('crs_wkt') or item.get('epsg')
        if crs_input:
            actual = CRS(base.with_suffix('.prj').read_text())
            expected = CRS(crs_input)
            # WKT1_ESRI may normalise datum/method names differently from WKT2
            # even when PROJ identifies both as the same EPSG CRS.
            same_authority = actual.to_authority() is not None and actual.to_authority() == expected.to_authority()
            assert same_authority or actual.equals(expected, ignore_axis_order=True), name
        else:
            assert not base.with_suffix('.prj').exists(), name
        types[item['kind']] += 1
        inventory.append({'图层': name, '类型': item['kind'], '要素数': item['features'],
                          'EPSG': item['epsg'], '换算系数': item['factor'], '空几何': nulls,
                          '无效面': invalid, '坐标判定': item['decision']})
    return {'status': 'PASS', 'source_hashes_match': True, 'product_hashes_match': True,
            'shape_dbf_counts_match': True, 'prj_readback_matches': True,
            'summary': manifest['summary'], 'layer_types': dict(types),
            'null_geometries': sum(e['空几何'] for e in inventory),
            'invalid_polygons': sum(e['无效面'] for e in inventory), 'inventory': inventory}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('dataset', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--inventory', type=Path)
    args = parser.parse_args()
    result = verify(args.dataset)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.inventory:
        with args.inventory.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(result['inventory'][0]))
            writer.writeheader()
            writer.writerows(result['inventory'])
    print(json.dumps({k: v for k, v in result.items() if k != 'inventory'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
