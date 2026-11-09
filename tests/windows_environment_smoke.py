"""Actual installed CLI/GUI regression with conflicting inherited GIS paths."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import native_fixtures as F
from mapgis_annotations import verify_dataset
from mapgis_annotations.runtime import is_windows_bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    assert is_windows_bundle(), 'Use the actual installed Windows interpreter'
    with tempfile.TemporaryDirectory(prefix='mapgis-external-env-') as temporary:
        root = Path(temporary)
        fake = root/'foreign-python'
        (fake/'qgis').mkdir(parents=True)
        (fake/'qgis/__init__.py').write_text('raise ImportError("FOREIGN_QGIS_MUST_NOT_LOAD")\n')
        env = dict(os.environ, PYTHONPATH=str(fake), QGIS_PREFIX_PATH=str(fake),
                   QT_PLUGIN_PATH=str(fake), QT_QPA_PLATFORM_PLUGIN_PATH=str(fake),
                   PROJ_DATA=str(fake), PROJ_LIB=str(fake), GDAL_DATA=str(fake), CONDA_PREFIX=str(fake))
        source = root/'原生 输入'
        source.mkdir()
        F.write_points(source/'labels.WT', [{'x':105, 'y':35, 'text':'测试ηγ#-2'}],
                       proj=0, ellipsoid=7, scale=0)
        config = root/'config.json'
        config.write_text(json.dumps({'render': {'enabled':True, 'width_mm':180, 'dpi':96}}))
        for mode in ('cli', 'isolated-launcher'):
            output = root/mode
            command = [sys.executable]
            if mode == 'isolated-launcher':
                command.append('-I')
                env['PYTHONHOME'] = str(fake)
            command += ['-m', 'mapgis_annotations', 'pipeline', str(source), str(output), '--config', str(config)]
            result = subprocess.run(command, env=env, capture_output=True, encoding='utf-8', timeout=120)
            assert result.returncode == 0, (mode, result.stdout, result.stderr)
            verify_dataset(output)
            assert (output/'map/map.pdf').stat().st_size > 1000
            assert json.loads((output/'map/export.json').read_text())['rendered_labels'] == 1
        # A real Tk window starts a separately isolated conversion worker.
        env.pop('PYTHONHOME', None)
        gui_report = root/'gui.json'
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('gui_smoke.py')), str(gui_report)],
                                env=env, capture_output=True, encoding='utf-8', timeout=120)
        assert result.returncode == 0, (result.stdout, result.stderr)
        gui = json.loads(gui_report.read_text())
        assert gui['status'] == 'PASS' and gui['background_subprocess']
    report = {'status':'PASS', 'foreign_python_qgis_ignored':True,
              'conflicting_qt_proj_gdal_paths_ignored':True, 'pythonhome_launcher_isolated':True,
              'native_to_pdf':True, 'gui_worker_and_preview':True}
    args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
