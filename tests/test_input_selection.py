import json
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import shapefile
import native_fixtures as F
from mapgis_annotations import AnnotationError, export_native, run_pipeline, verify_dataset
from mapgis_annotations.shapefiles import sha256
from mapgis_annotations.gui import Workbench
from mapgis_annotations.gui_job import JobRunner, make_job
import test_gui_job as gui_tests


class ExplicitFileSelection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='多选 文件 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.first, self.second = self.root/'甲', self.root/'乙'
        self.first.mkdir()
        self.second.mkdir()
        self.a = self.first/'labels.WT'
        self.b = self.second/'labels.WT'
        for i, path in enumerate((self.a, self.b)):
            F.write_points(path, [{'x':105+i*.01,'y':35,'text':'T#-2'}],
                           proj=0, ellipsoid=7, scale=0)
        (self.first/'unselected.WT').write_bytes(b'broken')

    def test_native_selection_deduplicates_paths_without_importing_siblings(self):
        output = self.root/'result'
        result = run_pipeline([self.a, self.b, self.a], output)
        self.assertEqual(result['native_summary']['layers'], 2)
        self.assertEqual(result['audit']['records'], 2)
        self.assertEqual(result['source'], [str(self.a), str(self.b)])
        manifest = json.loads((output/'native/native_export.json').read_text())
        self.assertEqual(set(manifest['layers']), {'labels_点', 'labels_点_2'})
        self.assertEqual(set(result['source_sha256']), {str(self.a), str(self.b)})
        verify_dataset(output)
        verify_dataset(output/'annotations')

    def test_projects_expand_and_shared_layers_only_appear_once(self):
        project = self.first/'map.MPJ'
        F.write_project(project, ['.\\labels.WT', '..\\乙\\labels.WT'])
        result = run_pipeline([project, self.a], self.root/'project')
        self.assertEqual(result['native_summary']['layers'], 2)
        self.assertIn(str(project), result['source_sha256'])
        verify_dataset(self.root/'project')
        native = export_native([project, self.a], self.root/'native-only')
        self.assertEqual(native['summary']['layers'], 2)

    def test_missing_project_layer_keeps_strict_policy_and_rolls_back(self):
        project = self.first/'missing.MPJ'
        F.write_project(project, ['.\\labels.WT', '.\\absent.WL'])
        with self.assertRaisesRegex(AnnotationError, 'missing layers'):
            run_pipeline([project, self.b], self.root/'strict')
        self.assertFalse((self.root/'strict').exists())
        result = run_pipeline([project, self.b], self.root/'partial', {'strict_native':False})
        self.assertEqual(result['native_summary']['missing_project_layers'], 1)

    def shp(self, folder, name):
        path = folder/(name+'.shp')
        with shapefile.Writer(str(path), encoding='utf-8') as writer:
            writer.field('TEXT', 'C', size=80)
            writer.point(105, 35)
            writer.record('测试T#-2')
        path.with_suffix('.CPG').write_text('UTF-8')
        return path

    def test_selected_shp_companions_and_provenance_survive_staging_cleanup(self):
        a, b = self.shp(self.first, 'one'), self.shp(self.second, 'two')
        ignored = self.shp(self.first, 'ignored')
        output = self.root/'shp-result'
        result = run_pipeline([a, b], output)
        self.assertEqual(result['audit']['records'], 2)
        self.assertEqual(result['annotations']['converted_layers'], 2)
        self.assertNotIn(str(ignored), result['source_sha256'])
        self.assertEqual(sha256(a), sha256(output/'input/one.shp'))
        self.assertIn(str(a.with_suffix('.CPG')), result['source_sha256'])
        verify_dataset(output)
        verify_dataset(output/'annotations')
        self.assertEqual(run_pipeline(a, self.root/'single-shp')['audit']['records'], 1)

    def test_ambiguous_or_mixed_selections_fail_without_output(self):
        a = self.shp(self.first, 'duplicate')
        b = self.shp(self.second, 'duplicate')
        for source, config in (([], None), ([self.a, a], None), ([a, b], None),
                               ([self.first, self.b], None), ([self.a], {'input_format':'shp'})):
            with self.subTest(source=source):
                with self.assertRaises(AnnotationError):
                    run_pipeline(source, self.root/'rejected', config)
                self.assertFalse((self.root/'rejected').exists())

    def test_output_protects_each_selected_input_folder(self):
        with self.assertRaisesRegex(AnnotationError, 'outside the input tree'):
            run_pipeline([self.a, self.b], self.second/'inside')
        self.assertFalse((self.second/'inside').exists())

    def test_gui_worker_transports_the_exact_unicode_selection_to_cli(self):
        runner = JobRunner()
        output = self.root/'worker'
        runner.start(make_job([self.a, self.b], output))
        event = gui_tests.DesktopJob.wait(self, runner)
        self.assertEqual(event['type'], 'complete', event)
        verify_dataset(output)
        manifest = json.loads((output/'manifest.json').read_text())
        self.assertEqual(manifest['native_summary']['layers'], 2)
        self.assertEqual(manifest['source'], [str(self.a), str(self.b)])

    def test_cli_json_selection_does_not_override_single_source_silently(self):
        selection = self.root/'所选文件.json'
        selection.write_text(json.dumps([str(self.a), str(self.b)]), encoding='utf-8-sig')
        command = [sys.executable, '-m', 'mapgis_annotations', 'pipeline']
        output = self.root/'cli'
        result = subprocess.run(command+[str(output), '--source-list', str(selection)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        verify_dataset(output)
        self.assertEqual(json.loads((output/'manifest.json').read_text())['audit']['records'], 2)
        result = subprocess.run(command+[str(self.a), str(self.root/'bad-cli'), '--source-list', str(selection)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('either source or --source-list', result.stderr)
        self.assertFalse((self.root/'bad-cli').exists())


class Value:
    def __init__(self, value=''):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class SelectionDialog(unittest.TestCase):
    def test_multiselect_cancel_manual_edit_and_folder_replacement(self):
        view = Workbench.__new__(Workbench)
        view.source = Value()
        view.selected_files, view.selection_text = (), ''
        selected = ('/maps/地质 图.WT', '/maps/构造;线.WL')
        dialog = SimpleNamespace(askopenfilenames=Mock(return_value=selected),
                                 askdirectory=Mock(return_value='/maps/other'))
        with patch.dict(sys.modules, {'tkinter':SimpleNamespace(filedialog=dialog)}):
            view.choose_source_file()
            self.assertEqual(view.source_value(), selected)
            self.assertIn('2 个文件', view.source.get())
            dialog.askopenfilenames.return_value = ()
            view.choose_source_file()
            self.assertEqual(view.source_value(), selected)
            view.source.set('/maps/manual.MPJ')
            self.assertEqual(view.source_value(), '/maps/manual.MPJ')
            view.choose_source_folder()
            self.assertEqual(view.source_value(), '/maps/other')
            self.assertFalse(view.selected_files)
