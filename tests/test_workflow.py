from pathlib import Path
import tempfile
import unittest
import shapefile
import json
from pyproj import CRS
from mapgis_annotations import AnnotationError, run_workflow, verify_dataset
from mapgis_annotations.cli import main


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root/'input'
        self.source.mkdir()
        with shapefile.Writer(str(self.source/'arbitrary'), shapeType=1, encoding='utf-8') as writer:
            writer.field('CUSTOM', 'C', 50)
            writer.point(1, 1)
            writer.record('A#-2')
        (self.source/'arbitrary.cpg').write_text('UTF-8')

    def tearDown(self):
        self.temp.cleanup()

    def config(self):
        return {'annotation_layers': ['arbitrary'], 'conversion': {'note_field': 'CUSTOM'}}

    def test_configured_batch_and_tamper_detection(self):
        output = self.root/'output'
        result = run_workflow(self.source, output, self.config())
        self.assertEqual(result['converted_records'], 1)
        self.assertEqual(verify_dataset(output)['status'], 'PASS')
        path = output/result['layers']['arbitrary']['path']
        path.write_bytes(path.read_bytes()+b'x')
        with self.assertRaisesRegex(AnnotationError, 'modified'):
            verify_dataset(output)

    def test_spatial_failure_rolls_back_batch(self):
        config = self.config()
        config['pairing'] = {'target_layers': ['arbitrary'], 'require_legend': False}
        with self.assertRaisesRegex(AnnotationError, 'Missing .prj'):
            run_workflow(self.source, self.root/'output', config)
        self.assertFalse((self.root/'output').exists())

    def test_malformed_nested_configuration_fails_before_writing(self):
        for values in [{'crosswalks':[{}]}, {'conversion':{'note_fields':[]}},
                       {'pairing':{'not_a_parameter':1}}]:
            with self.assertRaises(AnnotationError):
                run_workflow(self.source, self.root/'output', values)
            self.assertFalse((self.root/'output').exists())

    def test_unknown_config_and_no_layers_fail_cleanly(self):
        with self.assertRaises(AnnotationError):
            run_workflow(self.source, self.root/'out', {'typo': 1})
        self.assertEqual(main(['convert', str(self.source/'arbitrary.shp'), str(self.root/'out')]), 2)
        self.assertFalse((self.root/'out').exists())

    def test_different_region_names_fields_crs_and_ascii_patterns(self):
        for name, field, xy in [('map_labels', 'TEXT', (500, 500)),
                                ('legend_labels', 'CAPTION', (100, 100))]:
            with shapefile.Writer(str(self.source/name), shapeType=1, encoding='utf-8') as writer:
                writer.field(field, 'C', 50)
                for dx, text in [(0, 'ROCK'), (10, 'Unit#-2')]:
                    writer.point(xy[0]+dx, xy[1])
                    writer.record(text)
            (self.source/(name+'.cpg')).write_text('UTF-8')
            (self.source/(name+'.prj')).write_text(CRS.from_epsg(32648).to_wkt(version='WKT1_ESRI'))
        with shapefile.Writer(str(self.source/'geology'), shapeType=5) as writer:
            writer.field('ID', 'N')
            writer.poly([[(490,490),(490,520),(530,520),(530,490),(490,490)]])
            writer.record(1)
        (self.source/'geology.prj').write_text(CRS.from_epsg(32648).to_wkt(version='WKT1_ESRI'))
        profile = Path(__file__).resolve().parents[1]/'examples/generic.json'
        manifest = run_workflow(self.source, self.root/'generic', json.loads(profile.read_text()))
        self.assertEqual(manifest['converted_layers'], 2)
        self.assertEqual(manifest['spatial']['pairing']['map_labels']['matched'], 1)
        self.assertEqual(manifest['spatial']['crosswalks'][0]['rows'], 2)
        self.assertEqual(verify_dataset(self.root/'generic')['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
