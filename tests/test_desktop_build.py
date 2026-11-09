import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopBuild(unittest.TestCase):
    def test_offline_spec_contains_qgis_and_required_install_hook(self):
        builder = load('desktop_build',ROOT/'tools/build_desktop.py')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root/'app.whl'
            wheel.write_bytes(b'test wheel placeholder')
            spec = builder.make_context(wheel, root/'context', '0.4.0')
            self.assertTrue(any(item.startswith('qgis ') for item in spec['specs']))
            self.assertTrue(any(item.startswith('tk ') for item in spec['specs']))
            self.assertEqual(spec['installer_type'],'pkg')
            self.assertNotIn('post_install_desc',spec)
            self.assertTrue((root/'context'/spec['post_install']).exists())
            self.assertEqual(json.loads((root/'context/construct.yaml').read_text())['version'],'0.4.0')

    def test_launcher_uses_its_own_relocated_runtime(self):
        installer = load('desktop_install',ROOT/'packaging/install_desktop.py')
        with tempfile.TemporaryDirectory(prefix='path with spaces ') as temporary:
            prefix = Path(temporary)/'Applications/MapGIS2QGIS-0.4.0'
            app = installer.create_app(prefix, '0.4.0')
            with (app/'Contents/Info.plist').open('rb') as handle:
                info = plistlib.load(handle)
            self.assertEqual(info['CFBundleExecutable'],'mapgis2qgis')
            script = (app/'Contents/MacOS/mapgis2qgis').read_text()
            self.assertIn('"$MAPGIS_PREFIX/bin/python" -m mapgis_annotations gui',script)
            self.assertNotIn(temporary,script)
            self.assertTrue((prefix.parent/'MapGIS2QGIS-0.4.0.app').is_symlink())
