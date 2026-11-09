"""Read-only PyQGIS import diagnostics, usable with existing desktop installs.

Run with the installation's python.exe. No pip, data conversion, Qt application
or persistent environment changes are made. Each import probe is isolated.
"""
import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback


GIS_ENV = ('PYTHONHOME', 'PYTHONPATH', 'CONDA_PREFIX', 'QGIS_PREFIX_PATH',
           'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_PLATFORM',
           'GDAL_DATA', 'PROJ_DATA', 'PROJ_LIB')


def bundled_environment(environment, prefix, windows):
    """Use only this prefix and Windows system paths in the second probe."""
    env = dict(environment)
    for key in list(env):
        if key.upper() in GIS_ENV or key.upper().startswith('CONDA_'):
            del env[key]
    if windows:
        system = Path(env.get('SystemRoot', r'C:\Windows'))
        directories = (prefix, prefix/'Library/bin', prefix/'Library/lib', prefix/'Scripts',
                       system/'System32', system, system/'System32/Wbem')
        # Avoid duplicate PATH keys on Windows when inherited spelling is Path.
        for key in list(env):
            if key.upper() == 'PATH':
                del env[key]
        env['PATH'] = os.pathsep.join(str(p) for p in directories if p.is_dir())
    for root in (prefix/'Library', prefix):
        python = root/'python' if windows else root/'share/qgis/python'
        if (python/'qgis').is_dir():
            env['PYTHONPATH'] = str(python)
            env['QGIS_PREFIX_PATH'] = str(root)
            plugins = [p for p in (root/'qtplugins', root/'plugins') if p.is_dir()]
            if plugins:
                env['QT_PLUGIN_PATH'] = os.pathsep.join(map(str, plugins))
            break
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def snapshot():
    prefix = Path(sys.prefix)
    packages = []
    for name in ('qgis', 'python', 'pyqt', 'qt-main', 'pyproj', 'shapely', 'libgdal-core'):
        for path in sorted((prefix/'conda-meta').glob(name+'-*.json')):
            record = json.loads(path.read_text(encoding='utf-8'))
            if record.get('name') == name:
                packages.append({key: record.get(key) for key in ('name', 'version', 'build', 'subdir')})
    return {'python': sys.executable, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix,
            'python_version': sys.version, 'platform': sys.platform,
            'environment': {key: os.environ.get(key) for key in GIS_ENV},
            'packages': packages}


def probe():
    report = snapshot()
    imports = report['imports'] = []
    # Match the pipeline's ordering: configure, georeferencing/geometry, QGIS.
    for name in ('mapgis_annotations.runtime', 'pyproj', 'shapely.geometry', 'qgis.core'):
        entry = {'module': name}
        imports.append(entry)
        try:
            module = importlib.import_module(name)
            entry['file'] = getattr(module, '__file__', None)
            if name == 'mapgis_annotations.runtime':
                module.configure_runtime()
                from mapgis_annotations import __version__
                report['application_version'] = __version__
            elif name == 'pyproj':
                entry['epsg_4326'] = module.CRS.from_epsg(4326).to_epsg()
            elif name == 'shapely.geometry':
                entry['geometry_valid'] = module.Point(0, 0).buffer(1).is_valid
            else:
                entry['qgis_version'] = module.Qgis.QGIS_VERSION
            entry['status'] = 'PASS'
        except Exception as exc:
            entry.update(status='FAIL', error_type=type(exc).__name__, error=str(exc),
                         traceback=traceback.format_exc())
            # Continue to QGIS even if the app or a conversion dependency failed.
    report['configured_environment'] = {key: os.environ.get(key) for key in GIS_ENV}
    report['qgis_python_candidates'] = [str(p) for p in (
        Path(sys.prefix)/'Library/python/qgis',
        Path(sys.prefix)/'Library/share/qgis/python/qgis',
        Path(sys.prefix)/'share/qgis/python/qgis') if p.is_dir()]
    report['status'] = 'PASS' if all(item['status'] == 'PASS' for item in imports) else 'FAIL'
    return report


def run_probe(environment):
    command = [sys.executable, str(Path(__file__).resolve()), '--probe']
    try:
        result = subprocess.run(command, env=environment, capture_output=True,
                                encoding='utf-8', errors='replace', timeout=90)
    except subprocess.TimeoutExpired as exc:
        return {'status': 'TIMEOUT', 'error': str(exc)}
    try:
        report = json.loads(result.stdout)
    except ValueError:
        report = {'status': 'FAIL', 'stdout': result.stdout,
                  'error': 'Probe exited without a JSON report'}
    report['exit_code'] = result.returncode
    report['stderr'] = result.stderr
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('qgis-diagnostic.json'))
    parser.add_argument('--probe', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe(), ensure_ascii=True))
        return 0
    report = {'scope': 'Imports only; does not validate PDF export or modify installation/data',
              'launch_environment': snapshot()}
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    report['normal'] = run_probe(env)
    report['bundled_environment'] = run_probe(bundled_environment(env, Path(sys.prefix), os.name == 'nt'))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    # ASCII-safe output works in both legacy Windows consoles and PowerShell.
    for key in ('normal', 'bundled_environment'):
        item = report[key]
        print(key+': '+item['status'])
        for entry in item.get('imports', []):
            if entry['status'] != 'PASS':
                print(json.dumps(entry, ensure_ascii=True))
    print('Report: '+str(args.output.resolve()).encode('ascii', 'backslashreplace').decode('ascii'))
    return 0 if report['normal']['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
