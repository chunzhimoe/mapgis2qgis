"""Installed-runtime CRS JSON, reprojection separation and relocation checks."""
import json
from pathlib import Path
import shutil
import sys
import tempfile

import shapefile
from mapgis_annotations.runtime import configure_runtime
from mapgis_annotations import run_pipeline, verify_dataset
from mapgis_annotations.shapefiles import sha256


def check_reference(path):
    from pyproj import CRS
    report = json.loads(path.read_text(encoding='utf-8'))
    for value in report['crs_definitions'].values():
        if value['status'] == 'defined':
            assert CRS.from_json_dict(value['projjson']).equals(CRS(value['wkt']), ignore_axis_order=True)
    for item in report['layers'].values():
        assert (path.parent/report['dataset_root']/item['path']).is_file()
        if item['prj']:
            assert sha256(path.parent/report['dataset_root']/item['prj']) == item['prj_sha256']
    return report


def main():
    configure_runtime()
    from pyproj import CRS
    with tempfile.TemporaryDirectory(prefix='mapgis-crs-json-') as temporary:
        root = Path(temporary)
        source = root/'source'
        source.mkdir()
        for name in ('labels', 'unlocated'):
            with shapefile.Writer(str(source/name), encoding='utf-8') as writer:
                writer.field('TEXT','C', size=80)
                writer.point(1000, 1000)
                writer.record('测试T#-2')
                writer.point(1100, 1100)
                writer.record('ηγ')
            (source/(name+'.cpg')).write_text('UTF-8')
        (source/'labels.prj').write_text(CRS(3857).to_wkt(version='WKT1_ESRI'))
        before = {p.name:sha256(p) for p in source.iterdir()}
        output = root/'result'
        result = run_pipeline(source, output, {'render':{'enabled':True, 'width_mm':180, 'dpi':96,
                                                        'render_crs':'EPSG:4326'}})
        root_reference = check_reference(output/result['spatial_reference'])
        map_reference = check_reference(output/'map/spatial_reference.json')
        assert root_reference['main_crs_id'] == 'EPSG:3857'
        assert root_reference['render_reference']['crs_id'] == 'EPSG:4326'
        assert root_reference['layers']['unlocated']['crs_id'] is None
        assert root_reference['summary']['without_crs'] == ['unlocated']
        assert root_reference['layers']['labels']['native_conversion'] is None
        assert map_reference['render_reference']['crs_id'] == 'EPSG:4326'
        assert len(map_reference['render_reference']['extent_xy']) == 4
        assert map_reference['render_reference']['extent_xy'][2] < 1
        exported = json.loads((output/'map/export.json').read_text())
        assert exported['product_sha256']['spatial_reference.json'] == sha256(output/'map/spatial_reference.json')
        assert before == {p.name:sha256(p) for p in source.iterdir()}
        verify_dataset(output)
        relocated = root/'relocated'
        shutil.copytree(output, relocated)
        check_reference(relocated/'spatial_reference.json')
        check_reference(relocated/'map/spatial_reference.json')
        verify_dataset(relocated, verify_sources=False)
    report = {'status':'PASS', 'wkt_projjson_roundtrip':True, 'data_crs_preserved':True,
              'separate_render_crs':True, 'missing_crs_not_assigned':True,
              'json_product_hash_verified':True, 'relative_paths_survive_relocation':True,
              'source_bytes_unchanged':True}
    Path(sys.argv[1]).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
