import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopBuild(unittest.TestCase):
    def test_dmg_retries_only_transient_resource_busy(self):
        builder = load('desktop_build',ROOT/'tools/build_desktop.py')
        command = ['hdiutil','create','example.dmg']
        busy = subprocess.CompletedProcess(command, 1, '', 'hdiutil: create failed - Resource busy')
        ok = subprocess.CompletedProcess(command, 0, 'created\n', '')
        with patch.object(builder.subprocess,'run',side_effect=[busy,ok]) as run, patch.object(builder.time,'sleep') as sleep:
            builder.create_disk_image(command)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(3)
        denied = subprocess.CompletedProcess(command, 1, '', 'Permission denied')
        with patch.object(builder.subprocess,'run',return_value=denied) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                builder.create_disk_image(command)
        self.assertEqual(run.call_count, 1)

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

    def test_windows_installer_and_relative_launcher(self):
        builder = load('desktop_build',ROOT/'tools/build_desktop.py')
        installer = load('desktop_install',ROOT/'packaging/install_desktop.py')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root/'app.whl'
            wheel.write_bytes(b'test wheel placeholder')
            spec = builder.make_context(wheel,root/'context','0.4.0','win-64')
            self.assertEqual(spec['installer_type'],'exe')
            self.assertEqual(spec['post_install'],'post_install.bat')
            self.assertNotIn('pkg_name',spec)
            launcher = installer.create_windows_launcher(root,shortcuts=False)
            self.assertIn('"%~dp0pythonw.exe"',launcher.read_text())
            self.assertIn('-I -m mapgis_annotations gui',launcher.read_text())

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

    def test_windows_shortcut_with_constructor_restricted_path(self):
        installer = load('desktop_install',ROOT/'packaging/install_desktop.py')
        with tempfile.TemporaryDirectory(prefix='windows install ') as temporary:
            root = Path(temporary).resolve()
            powershell = root/'Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
            powershell.parent.mkdir(parents=True)
            powershell.touch()
            prefix = root/'MapGIS2QGIS'
            prefix.mkdir()
            with patch.dict(os.environ, {'SystemRoot':str(root/'Windows'),'PATH':str(root/'Windows/System32')}, clear=True):
                with patch.object(installer.subprocess,'run') as run:
                    installer.create_windows_launcher(prefix)
            self.assertEqual(run.call_args.args[0][0], str(powershell))
            self.assertEqual(run.call_args.kwargs['env']['MAPGIS_INSTALL_PREFIX'], str(prefix))
            self.assertTrue(run.call_args.kwargs['check'])
            self.assertIn("$s.Arguments='-I -m mapgis_annotations gui'", run.call_args.args[0][-1])
