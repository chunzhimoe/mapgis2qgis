import json
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import shapefile
import native_fixtures as F
from pyproj import CRS

from mapgis_annotations import AnnotationError, export_native, run_pipeline, verify_dataset
from mapgis_annotations.shapefiles import sha256
from mapgis_annotations.spatial_reference import spatial_reference_report


class SpatialReferenceMetadata(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.data = self.root/'data'
        self.data.mkdir()

    def layer(self, name, crs=None):
        path = self.data/(name+'.shp')
        with shapefile.Writer(str(path)) as writer:
            writer.field('ID','N')
            writer.point(1, 2)
            writer.record(1)
        if crs is not None:
            path.with_suffix('.PRJ').write_text(crs.to_wkt(version='WKT1_ESRI'), encoding='utf-8')
        return path

    def test_native_factor_missing_layer_and_standard_projjson_round_trip(self):
        F.write_points(self.data/'main.WT', [{'x':14000,'y':80000,'text':'T#-2'},
                                            {'x':14020,'y':80020,'text':'测试'}],
                       proj=5, ellipsoid=1, scale=50000, cm=93)
        F.write_points(self.data/'inset.WT', [{'x':1,'y':2,'text':'未定位'}],
                       proj=0, ellipsoid=0, scale=0, cm=0)
        output = self.root/'native'
        native = export_native(self.data, output)
        before = {p.name:sha256(p) for p in output.glob('*.shp')}
        report = spatial_reference_report(output, native=native, input_format='native')
        self.assertEqual(report['main_crs_id'], 'EPSG:21456')
        self.assertEqual(report['summary']['with_crs'], 1)
        self.assertEqual(report['summary']['without_crs'], ['inset_点'])
        self.assertEqual(report['data_crs_status'], 'partial')
        reference = report['crs_definitions']['EPSG:21456']
        self.assertEqual(reference['unit'], 'metre')
        self.assertEqual(CRS.from_json_dict(reference['projjson']).to_epsg(), 21456)
        self.assertEqual(report['layers']['main_点']['native_conversion']['factor'], 50)
        self.assertEqual(report['layers']['inset_点']['native_conversion']['factor'], 1)
        self.assertIsNone(report['layers']['inset_点']['crs_id'])
        self.assertEqual(before, {p.name:sha256(p) for p in output.glob('*.shp')})
        json.dumps(report, allow_nan=False)

    def test_custom_crs_without_epsg_retains_conic_parameters(self):
        custom = CRS.from_proj4('+proj=aea +lon_0=105.12345 +lat_0=32.1 +lat_1=24.2 +lat_2=47.8 '
                                '+x_0=123456.7 +y_0=654321.2 +datum=WGS84 +units=m')
        self.layer('custom', custom)
        report = spatial_reference_report(self.data)
        self.assertEqual(report['summary']['with_crs'], 1)
        reference = report['crs_definitions'][report['main_crs_id']]
        self.assertIsNone(reference['auth_id'])
        self.assertIsNotNone(reference['projjson'])
        self.assertTrue(CRS.from_json_dict(reference['projjson']).equals(custom, ignore_axis_order=True))
        self.assertIn('105.12345', reference['wkt'])
        self.assertIn('654321.2', reference['wkt'])

    def test_gb18030_local_crs_names_and_engineering_units_are_preserved(self):
        path = self.layer('local')
        wkt = ('LOCAL_CS["本地矿区",LOCAL_DATUM["本地基准",0],UNIT["metre",1],'
               'AXIS["Easting",EAST],AXIS["Northing",NORTH]]')
        path.with_suffix('.prj').write_bytes(wkt.encode('gb18030'))
        report = spatial_reference_report(self.data)
        item = report['layers']['local']
        self.assertEqual(item['prj_decode_codec'], 'gb18030')
        self.assertEqual(item['crs_status'], 'defined')
        definition = report['crs_definitions'][item['crs_id']]
        self.assertIsNone(definition['auth_id'])
        self.assertEqual(definition['name'], '本地矿区')
        self.assertEqual(definition['unit'], 'metre')
        self.assertEqual(CRS.from_json_dict(definition['projjson']).name, '本地矿区')

    def test_mixed_data_crs_does_not_invent_one_main_crs(self):
        self.layer('projected', CRS(3857))
        self.layer('geographic', CRS(4326))
        report = spatial_reference_report(self.data)
        self.assertIsNone(report['main_crs_id'])
        self.assertEqual(report['data_crs_status'], 'mixed')
        self.assertEqual(report['summary']['data_crs_count'], 2)
        self.assertEqual(report['crs_definitions']['EPSG:4326']['unit'].casefold(), 'degree')
        self.assertAlmostEqual(report['crs_definitions']['EPSG:4326']['axis_info'][0]['unit_conversion_factor'],
                               0.0174532925199433)

    def test_render_crs_is_separate_from_source_data_and_unknown_layer(self):
        self.layer('main', CRS(3857))
        self.layer('unknown')
        report = spatial_reference_report(self.data, path_prefix='data',
            rendering={'crs_wkt':CRS(4326).to_wkt(), 'extent_xy':[1,2,3,4]})
        self.assertEqual(report['main_crs_id'], 'EPSG:3857')
        self.assertEqual(report['render_reference']['crs_id'], 'EPSG:4326')
        self.assertEqual(report['render_reference']['extent_xy'], [1,2,3,4])
        self.assertEqual(report['layers']['main']['path'], 'data/main.shp')
        self.assertEqual(report['layers']['main']['prj'], 'data/main.PRJ')
        self.assertIsNone(report['layers']['unknown']['crs_id'])
        self.assertIsNone(report['layers']['main']['native_conversion'])

    def test_invalid_prj_is_retained_without_guessing_or_changing_coordinates(self):
        a, b = self.layer('bad'), self.layer('binary')
        a.with_suffix('.prj').write_text('not a CRS')
        b.with_suffix('.prj').write_bytes(b'\xff\xff')
        report = spatial_reference_report(self.data)
        self.assertEqual(report['summary']['invalid_crs'], ['bad', 'binary'])
        self.assertEqual(report['summary']['with_crs'], 0)
        self.assertIsNone(report['main_crs_id'])
        self.assertIn('error', report['layers']['binary'])
        self.assertEqual(report['crs_definitions'][report['layers']['bad']['crs_id']]['source_wkt'], 'not a CRS')

    def test_missing_and_unparsed_crs_keep_optional_pyproj_behavior(self):
        self.layer('missing')
        with patch('mapgis_annotations.spatial_reference._load_pyproj', side_effect=AssertionError('must stay optional')):
            report = spatial_reference_report(self.data)
        self.assertEqual(report['summary']['without_crs'], ['missing'])
        self.layer('known', CRS(4326))
        with patch('mapgis_annotations.spatial_reference._load_pyproj', side_effect=ImportError('no pyproj')):
            report = spatial_reference_report(self.data)
        self.assertEqual(report['summary']['unparsed_crs'], ['known'])
        self.assertIsNone(report['main_crs_id'])
        self.assertIn('GEOGCS', report['crs_definitions'][report['layers']['known']['crs_id']]['wkt'])

    def test_manifest_cannot_read_a_layer_outside_its_dataset(self):
        with self.assertRaises(AnnotationError):
            spatial_reference_report(self.data, dataset={'layers':{'bad':{'path':'../escape.shp'}}})

    def test_pipeline_always_exports_metadata_and_protects_it_with_product_hashes(self):
        self.layer('main', CRS(4326))
        self.layer('unknown')
        output = self.root/'pipeline'
        result = run_pipeline(self.data, output)
        self.assertEqual(result['spatial_reference'], 'spatial_reference.json')
        metadata = json.loads((output/result['spatial_reference']).read_text())
        self.assertEqual(metadata['dataset_root'], '.')
        self.assertEqual(metadata['summary']['without_crs'], ['unknown'])
        for item in metadata['layers'].values():
            self.assertTrue((output/metadata['dataset_root']/item['path']).is_file())
        verify_dataset(output)
        (output/result['spatial_reference']).write_text('{}')
        with self.assertRaisesRegex(AnnotationError, 'Product missing or modified'):
            verify_dataset(output)

    def test_native_without_georeference_exports_unknown_crs_without_pyproj(self):
        F.write_points(self.data/'paper.WT', [{'x':1,'y':2,'text':'T#-2'}])
        with patch('mapgis_annotations.spatial_reference._load_pyproj', side_effect=AssertionError('must stay optional')):
            native = export_native(self.data, self.root/'paper-output', georeference=False)
        report = json.loads((self.root/'paper-output'/native['spatial_reference']).read_text())
        self.assertEqual(report['summary']['with_crs'], 0)
        self.assertIsNone(report['main_crs_id'])
        self.assertEqual(report['layers']['paper_点']['native_conversion']['factor'], 1)

    def test_backfill_keeps_existing_verified_products_unchanged_and_refuses_overwrite(self):
        self.layer('main', CRS(4326))
        output = self.root/'pipeline'
        run_pipeline(self.data, output)
        before = {p.relative_to(output).as_posix():sha256(p) for p in output.rglob('*') if p.is_file()}
        spec = importlib.util.spec_from_file_location('export_reference',
            Path(__file__).resolve().parents[1]/'tools/export_spatial_reference.py')
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        sidecar = self.root/'existing-reference.json'
        report = tool.export_existing(output, sidecar)
        self.assertEqual(report['main_crs_id'], 'EPSG:4326')
        self.assertEqual(before, {p.relative_to(output).as_posix():sha256(p) for p in output.rglob('*') if p.is_file()})
        self.assertTrue((sidecar.parent/report['dataset_root']/report['layers']['main']['path']).is_file())
        with self.assertRaises(AnnotationError):
            tool.export_existing(output, sidecar)
        with self.assertRaises(AnnotationError):
            tool.export_existing(output, output/'extra.json')
