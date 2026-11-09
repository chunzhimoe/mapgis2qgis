"""Discover the bundled Conda QGIS runtime without fixed installation paths."""
import os
from pathlib import Path
import sys
import subprocess

_DLL_HANDLES = []

_GIS_ENV = ('PYTHONHOME', 'PYTHONPATH', 'CONDA_PREFIX', 'QGIS_PREFIX_PATH',
            'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_PLATFORM',
            'GDAL_DATA', 'PROJ_DATA', 'PROJ_LIB')


def is_windows_bundle(prefix=None):
    """Restrict isolation to a Windows interpreter with its own Conda QGIS."""
    prefix = Path(sys.prefix if prefix is None else prefix)
    return (sys.platform == 'win32' and (prefix/'Library/python/qgis').is_dir()
            and any((prefix/'conda-meta').glob('qgis-*.json')))


def desktop_environment(environment=None, prefix=None):
    """Create a private, relocatable DLL/Python/Qt environment for the bundle.

    Other Python/QGIS installations and non-Windows callers retain their env.
    No system settings are modified. Keep the standalone 0.4.3 recovery tool's
    equivalent environment covered by tests for compatibility.
    """
    prefix = Path(sys.prefix if prefix is None else prefix)
    env = dict(os.environ if environment is None else environment)
    if not is_windows_bundle(prefix):
        return env
    for key in list(env):
        if key.upper() in _GIS_ENV or key.upper().startswith('CONDA_') or key.upper() == 'PATH':
            del env[key]
    system = Path(env.get('SystemRoot', r'C:\Windows'))
    directories = (prefix, prefix/'Library/bin', prefix/'Library/lib', prefix/'Scripts',
                   system/'System32', system, system/'System32/Wbem')
    env['PATH'] = os.pathsep.join(str(p) for p in directories if p.is_dir())
    library = prefix/'Library'
    env['PYTHONPATH'] = str(library/'python')
    env['QGIS_PREFIX_PATH'] = str(library)
    plugins = [p for p in (library/'qtplugins', library/'plugins') if p.is_dir()]
    if plugins:
        env['QT_PLUGIN_PATH'] = os.pathsep.join(map(str, plugins))
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def relaunch_bundled_cli(argv=None):
    """Start a fresh isolated Python before GIS DLLs can be loaded incorrectly."""
    if not is_windows_bundle():
        return None
    env = desktop_environment()
    if sys.flags.isolated and env == dict(os.environ):
        return None
    return subprocess.call([sys.executable, '-I', '-m', 'mapgis_annotations',
                            *(sys.argv[1:] if argv is None else argv)], env=env)


def configure_runtime():
    prefix = Path(sys.prefix)
    if is_windows_bundle(prefix):
        env = desktop_environment()
        for key in list(os.environ):
            if key not in env:
                del os.environ[key]
        os.environ.update(env)
    for directory in (prefix/'share/qgis/python', prefix/'Library/python', prefix/'Library/share/qgis/python'):
        if (directory/'qgis').is_dir():
            if str(directory) in sys.path:
                sys.path.remove(str(directory))
            sys.path.insert(0, str(directory))
    for root in (prefix, prefix/'Library'):
        if (root/'share/qgis').is_dir():
            os.environ.setdefault('QGIS_PREFIX_PATH', str(root))
        if (root/'share/proj/proj.db').is_file():
            os.environ.setdefault('PROJ_DATA', str(root/'share/proj'))
        if (root/'share/gdal').is_dir():
            os.environ.setdefault('GDAL_DATA', str(root/'share/gdal'))
    if os.name == 'nt':
        directories = [prefix/'Library/bin', prefix/'Library/lib', prefix/'Scripts', prefix]
        os.environ['PATH'] = os.pathsep.join(str(p) for p in directories if p.is_dir()) + os.pathsep + os.environ.get('PATH', '')
        if hasattr(os, 'add_dll_directory') and not _DLL_HANDLES:
            for directory in directories:
                if directory.is_dir():
                    _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
