import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from mapgis_annotations import runtime


class BundledWindowsRuntime(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='runtime with spaces ')
        self.root = Path(self.temp.name)
        self.prefix = self.root/'MapGIS2QGIS'
        for name in ('Library/python/qgis', 'Library/bin', 'Library/qtplugins', 'conda-meta'):
            (self.prefix/name).mkdir(parents=True)
        (self.prefix/'conda-meta/qgis-3.40-test.json').write_text('{}')
        self.system = self.root/'Windows'
        (self.system/'System32').mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_isolation_requires_windows_and_actual_bundled_qgis(self):
        with patch.object(runtime.sys, 'platform', 'win32'):
            self.assertTrue(runtime.is_windows_bundle(self.prefix))
            self.assertFalse(runtime.is_windows_bundle(self.root))
        with patch.object(runtime.sys, 'platform', 'darwin'):
            self.assertFalse(runtime.is_windows_bundle(self.prefix))

    def test_clean_environment_matches_verified_043_recovery_and_is_idempotent(self):
        spec = importlib.util.spec_from_file_location('recovery',
            Path(__file__).resolve().parents[1]/'tools/qgis_diagnose.py')
        recovery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(recovery)
        original = {'SystemRoot': str(self.system), 'PATH': 'foreign-runtime',
                    'PYTHONPATH': 'foreign-python', 'PYTHONHOME': 'foreign-home',
                    'CONDA_PREFIX': 'foreign-conda', 'CONDA_DLL_SEARCH_MODIFICATION_ENABLE': '1',
                    'PROJ_DATA': 'foreign-proj', 'QT_PLUGIN_PATH': 'foreign-qt',
                    'QGIS_PREFIX_PATH': 'foreign-qgis', 'TEMP': str(self.root)}
        before = dict(original)
        with patch.object(runtime.sys, 'platform', 'win32'):
            env = runtime.desktop_environment(original, self.prefix)
            self.assertEqual(env, recovery.bundled_environment(original, self.prefix, True))
            self.assertEqual(env, runtime.desktop_environment(env, self.prefix))
        self.assertEqual(original, before)
        self.assertNotIn('foreign', str(env))
        self.assertEqual(env['TEMP'], str(self.root))

    def test_other_environments_remain_unchanged(self):
        env = {'PATH': 'external', 'QGIS_PREFIX_PATH': 'custom-qgis'}
        with patch.object(runtime, 'is_windows_bundle', return_value=False):
            self.assertEqual(runtime.desktop_environment(env), env)
            self.assertIsNone(runtime.relaunch_bundled_cli(['parse', 'A']))

    def test_cli_restarts_once_before_importing_native_dependencies(self):
        clean = {'PATH': 'own-runtime'}
        with patch.object(runtime, 'is_windows_bundle', return_value=True), \
                patch.object(runtime, 'desktop_environment', return_value=clean), \
                patch.object(runtime.sys, 'flags', SimpleNamespace(isolated=1)), \
                patch.dict(os.environ, clean, clear=True), \
                patch.object(runtime.subprocess, 'call', return_value=2) as call:
            self.assertIsNone(runtime.relaunch_bundled_cli(['parse', 'A']))
            call.assert_not_called()
            os.environ['QGIS_PREFIX_PATH'] = 'foreign'
            self.assertEqual(runtime.relaunch_bundled_cli(['parse', 'A']), 2)
            self.assertEqual(call.call_args.args[0][1:], ['-I', '-m', 'mapgis_annotations', 'parse', 'A'])
            self.assertEqual(call.call_args.kwargs['env'], clean)
