import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import shapefile
import native_fixtures as F
from mapgis_annotations import (AnnotationError, PipelineCancelled, PipelineConfig, run_pipeline, verify_dataset)


class CompletePipeline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root/'input with spaces'
        self.source.mkdir()
        F.write_points(self.source/'any.WT', [{'x':105,'y':35,'text':'A#-2'}], proj=0, ellipsoid=7, scale=0)

    def tearDown(self):
        self.temp.cleanup()

    def test_published_paths_and_hashes_survive_temporary_cleanup(self):
        output = self.root/'result'
        events = []
        result = run_pipeline(self.source, output, progress=events.append)
        self.assertEqual(result['annotations']['changed_notes'], 1)
        self.assertEqual(events[-1]['percent'], 100)
        verify_dataset(output)
        verify_dataset(output/'annotations')
        text = (output/'annotations/manifest.json').read_text()
        self.assertNotIn('.mapgis-pipeline-', text)
        self.assertTrue(all(Path(p).exists() for p in json.loads(text)['source_sha256']))
        self.assertTrue((output/'inventory.csv').is_file())
        with self.assertRaises(AnnotationError):
            run_pipeline(self.source, output)

    def test_cancellation_rolls_back_before_publication(self):
        output = self.root/'cancelled'
        state = []
        def progress(event):
            state.append(event['stage'])
        with self.assertRaises(PipelineCancelled):
            run_pipeline(self.source, output, progress=progress, cancelled=lambda:'annotations' in state)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob('.mapgis-pipeline-*')))

    def test_render_failure_rolls_back_every_stage(self):
        with patch('mapgis_annotations.qgis_adapter.export_project', side_effect=AnnotationError('render failed')):
            with self.assertRaisesRegex(AnnotationError, 'render failed'):
                run_pipeline(self.source, self.root/'failed', {'render':{'enabled':True}})
        self.assertFalse((self.root/'failed').exists())

    def test_plain_geometry_without_annotations_and_no_crs(self):
        source = self.root/'shp'
        source.mkdir()
        with shapefile.Writer(str(source/'lines'), shapeType=3) as writer:
            writer.field('ID','N')
            writer.line([[(1,2),(3,4)]])
            writer.record(1)
        result = run_pipeline(source, self.root/'plain')
        self.assertEqual(result['input_format'], 'shp')
        self.assertEqual(result['annotations']['converted_layers'], 0)
        verify_dataset(self.root/'plain')

    def test_old_profile_and_bad_configuration(self):
        profile = PipelineConfig.from_dict({'conversion':{'note_field':'注记'}})
        self.assertEqual(profile.annotations['conversion']['note_field'], '注记')
        for value in ({'render':{'enabled':'yes'}}, {'wrong':1}, {'native':{'unknown':1}}, {'input_format':'guess'}):
            with self.assertRaises(AnnotationError):
                run_pipeline(self.source, self.root/'bad', value)

    def test_unreadable_native_fails_strict_and_requires_explicit_partial(self):
        (self.source/'bad.WT').write_bytes(b'broken')
        with self.assertRaisesRegex(AnnotationError, 'unreadable'):
            run_pipeline(self.source, self.root/'strict')
        result = run_pipeline(self.source, self.root/'partial', {'strict_native':False})
        self.assertEqual(result['native_summary']['unreadable'], 1)
