import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'qgis_diagnose', Path(__file__).resolve().parents[1]/'tools/qgis_diagnose.py')
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


class QgisDiagnostics(unittest.TestCase):
    def test_windows_probe_isolated_without_modifying_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prefix = root/'installation with spaces'
            for relative in ('Library/python/qgis', 'Library/qtplugins', 'Library/bin'):
                (prefix/relative).mkdir(parents=True)
            system = root/'Windows'
            (system/'System32').mkdir(parents=True)
            original = {'SystemRoot': str(system), 'Path': 'foreign-conda',
                        'PYTHONHOME': 'foreign-python', 'CONDA_PREFIX': 'foreign-conda',
                        'QGIS_PREFIX_PATH': 'foreign-qgis', 'PROJ_DATA': 'foreign-proj',
                        'TEMP': str(root)}
            before = dict(original)
            result = diagnostic.bundled_environment(original, prefix, True)
            self.assertEqual(original, before)
            self.assertNotIn('foreign', str(result))
            self.assertNotIn('Path', result)
            self.assertEqual(result['PYTHONPATH'], str(prefix/'Library/python'))
            self.assertEqual(result['QGIS_PREFIX_PATH'], str(prefix/'Library'))
            self.assertEqual(result['QT_PLUGIN_PATH'], str(prefix/'Library/qtplugins'))
            self.assertEqual(result['TEMP'], str(root))

    def test_exact_qgis_import_error_and_traceback_retained(self):
        runtime = SimpleNamespace(__file__='runtime.py', configure_runtime=lambda: None)
        proj = SimpleNamespace(__file__='pyproj.py', CRS=SimpleNamespace(
            from_epsg=lambda _: SimpleNamespace(to_epsg=lambda: 4326)))
        geometry = SimpleNamespace(__file__='geometry.py', Point=lambda *_: SimpleNamespace(
            buffer=lambda _: SimpleNamespace(is_valid=True)))
        modules = {'mapgis_annotations.runtime': runtime, 'pyproj': proj, 'shapely.geometry': geometry}
        def importing(name):
            if name == 'qgis.core':
                raise ImportError('DLL load failed while importing _core: example.dll missing')
            return modules[name]
        with patch.object(diagnostic, 'snapshot', return_value={}), \
                patch.object(diagnostic.importlib, 'import_module', side_effect=importing):
            result = diagnostic.probe()
        self.assertEqual(result['status'], 'FAIL')
        failure = result['imports'][-1]
        self.assertIn('example.dll missing', failure['error'])
        self.assertIn('ImportError:', failure['traceback'])
        self.assertEqual([r['status'] for r in result['imports'][:-1]], ['PASS']*3)

    def test_native_crash_does_not_erase_parent_report(self):
        completed = SimpleNamespace(stdout='', stderr='native DLL crash', returncode=-1)
        with patch.object(diagnostic.subprocess, 'run', return_value=completed):
            report = diagnostic.run_probe(dict(os.environ))
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['exit_code'], -1)
        self.assertEqual(report['stderr'], 'native DLL crash')
