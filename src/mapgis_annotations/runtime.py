"""Discover the bundled Conda QGIS runtime without fixed installation paths."""
import os
from pathlib import Path
import sys

_DLL_HANDLES = []


def configure_runtime():
    prefix = Path(sys.prefix)
    for directory in (prefix/'share/qgis/python', prefix/'Library/python', prefix/'Library/share/qgis/python'):
        if (directory/'qgis').is_dir() and str(directory) not in sys.path:
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
