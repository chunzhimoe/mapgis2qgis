import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import native_fixtures as F
from mapgis_annotations.gui import Workbench
from mapgis_annotations.gui_job import make_job
from mapgis_annotations.pipeline import PipelineConfig

ROOT = Path(__file__).resolve().parents[1]
PRESETS = ROOT/'examples/profiles'


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class ProfileSelection(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root/'input'
        self.source.mkdir()
        F.write_points(self.source/'labels.WT', [{'x':105,'y':35,'text':'测试'}],
                       proj=0, ellipsoid=7, scale=0)
        self.view = SimpleNamespace(profile=Value(''), render=Value(True), size=Value('8'),
                                    unit=Value('points'), width=Value('700'), dpi=Value('200'), auto_font=Value(True))
        self.messages = SimpleNamespace(showerror=Mock())
        self.tk = patch.dict(sys.modules, {'tkinter':SimpleNamespace(messagebox=self.messages)})
        self.tk.start()
        self.addCleanup(self.tk.stop)

    def load(self, path):
        Workbench.load_profile(self.view, path)
        self.messages.showerror.assert_not_called()

    def job(self):
        return make_job(self.source, self.root/'output', self.view.profile.get(),
                        render=self.view.render.get(), width=self.view.width.get(), dpi=self.view.dpi.get(),
                        font_size=self.view.size.get(), font_unit=self.view.unit.get(),
                        auto_font_size=self.view.auto_font.get())

    def test_loading_partial_bom_profile_keeps_drawing_and_user_sizes(self):
        path = self.root/'partial.json'
        path.write_text(json.dumps({'strict_native':False}), encoding='utf-8-sig')
        self.load(path)
        job = self.job()
        self.assertFalse(job.config['strict_native'])
        self.assertTrue(job.config['render']['enabled'])
        self.assertEqual(job.config['render']['width_mm'], 700)
        self.assertEqual(job.config['render']['dpi'], 200)
        self.assertEqual(job.config['render']['font_size'], 8)

    def test_full_preset_changes_only_supplied_render_settings(self):
        self.load(PRESETS/'03_quick_preview_pdf.json')
        job = self.job()
        self.assertTrue(job.config['render']['enabled'])
        self.assertEqual(job.config['render']['dpi'], 96)
        self.assertEqual(job.config['render']['width_mm'], 300)
        self.load(PRESETS/'04_data_only.json')
        self.assertFalse(self.job().config['render']['enabled'])

    def test_invalid_profile_keeps_current_gui_settings(self):
        path = self.root/'invalid.json'
        path.write_text('{"render":{"enabled":"yes"}}', encoding='utf-8')
        Workbench.load_profile(self.view, path)
        self.messages.showerror.assert_called_once()
        self.assertEqual(self.view.profile.get(), '')
        self.assertTrue(self.view.render.get())
        self.assertEqual(self.view.width.get(), '700')

    def test_preset_input_format_is_kept_and_explicit_override_wins(self):
        path = PRESETS/'05_shp_full_pdf.json'
        self.load(path)
        self.assertEqual(self.job().config['input_format'], 'shp')
        override = make_job(self.source, self.root/'other', path, input_format='auto')
        self.assertEqual(override.config['input_format'], 'auto')

    def test_gui_auto_font_option_survives_partial_profile_and_can_be_disabled(self):
        self.load(PRESETS/'07_auto_full_pdf.json')
        self.assertTrue(self.job().config['render']['auto_font_size'])
        self.view.auto_font.set(False)
        self.load(PRESETS/'01_generic_full_pdf.json')
        self.assertFalse(self.job().config['render']['auto_font_size'])

    def test_presets_validate_and_zip_contains_exact_reviewed_files(self):
        paths = sorted(PRESETS.glob('*.json'))
        self.assertEqual(len(paths), 7)
        for path in paths:
            with self.subTest(path=path.name):
                PipelineConfig.from_dict(json.loads(path.read_text(encoding='utf-8'))).validate()
        spec = importlib.util.spec_from_file_location('package_profiles', ROOT/'tools/package_profiles.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.package_profiles(self.root/'profiles.zip')
        with zipfile.ZipFile(result) as archive:
            self.assertIsNone(archive.testzip())
            expected = [PRESETS/'README.md', *paths]
            self.assertEqual(set(archive.namelist()), {'MapGIS2QGIS-profiles/'+p.name for p in expected})
            for path in expected:
                self.assertEqual(archive.read('MapGIS2QGIS-profiles/'+path.name), path.read_bytes())
