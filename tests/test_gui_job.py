import json
from pathlib import Path
import queue
import tempfile
import time
import unittest

import native_fixtures as F
from mapgis_annotations import AnnotationError, verify_dataset
from mapgis_annotations.gui_job import JobRunner, make_job


class DesktopJob(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root/'输入 文件'
        self.source.mkdir()
        F.write_points(self.source/'labels.WT', [{'x':105,'y':35,'text':'A#-2'}], proj=0, ellipsoid=7, scale=0)

    def tearDown(self):
        self.temp.cleanup()

    def wait(self, runner):
        end = time.monotonic()+30
        terminal = None
        while time.monotonic() < end:
            try:
                event = runner.events.get(timeout=.2)
            except queue.Empty:
                continue
            if event['type'] in ('complete','error','cancelled'):
                terminal = event
                break
        runner.thread.join(timeout=5)
        self.assertIsNotNone(terminal)
        self.assertFalse(runner.running)
        return terminal

    def test_subprocess_handles_unicode_paths_and_reports_result(self):
        runner = JobRunner()
        runner.start(make_job(str(self.source), str(self.root/'输出 结果')))
        event = self.wait(runner)
        self.assertEqual(event['type'],'complete', event)
        verify_dataset(self.root/'输出 结果')

    def test_cancel_before_processing_publishes_nothing(self):
        runner = JobRunner()
        runner.start(make_job(str(self.source), str(self.root/'cancelled')))
        runner.cancel()
        self.assertEqual(self.wait(runner)['type'],'cancelled')
        self.assertFalse((self.root/'cancelled').exists())

    def test_bad_settings_and_inside_input_are_rejected(self):
        for options in ({'dpi':'bad'}, {'factor':'nan'}, {'font_size':'0'}, {'epsg':'abc'}):
            with self.assertRaises(AnnotationError):
                make_job(str(self.source), str(self.root/'out'), **options)
        with self.assertRaises(AnnotationError):
            make_job(str(self.source), str(self.source/'inside'))

    def test_profile_remains_unchanged(self):
        path = self.root/'profile.json'
        path.write_text(json.dumps({'render':{'enabled':True,'details':[]}}))
        before = path.read_bytes()
        job = make_job(str(self.source), str(self.root/'out'), str(path), render=False)
        self.assertFalse(job.config['render']['enabled'])
        self.assertEqual(before, path.read_bytes())
