"""Install the bundled pure-Python wheel offline and create the macOS app."""
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


def create_app(prefix, version):
    prefix = Path(prefix).resolve()
    app = prefix/'MapGIS2QGIS.app'
    contents = app/'Contents'
    binary = contents/'MacOS/mapgis2qgis'
    binary.parent.mkdir(parents=True, exist_ok=True)
    info = {'CFBundleName':'MapGIS2QGIS', 'CFBundleDisplayName':'MapGIS2QGIS',
            'CFBundleIdentifier':'io.github.chunzhimoe.mapgis2qgis',
            'CFBundleVersion':version, 'CFBundleShortVersionString':version,
            'CFBundleExecutable':'mapgis2qgis', 'CFBundlePackageType':'APPL',
            'NSHighResolutionCapable':True, 'LSMinimumSystemVersion':'12.0'}
    with (contents/'Info.plist').open('wb') as handle:
        plistlib.dump(info, handle)
    binary.write_text('#!/bin/bash\nset -e\nAPP_BIN_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
                      'MAPGIS_PREFIX="$(cd "$APP_BIN_DIR/../../.." && pwd)"\n'
                      'exec "$MAPGIS_PREFIX/bin/python" -m mapgis_annotations gui\n', encoding='utf-8')
    binary.chmod(0o755)
    # The installer creates its own versioned prefix under Applications.
    # A new convenience symlink must never replace somebody else's app.
    if prefix.parent.name == 'Applications':
        shortcut = prefix.parent/('MapGIS2QGIS-'+version+'.app')
        if not shortcut.exists() and not shortcut.is_symlink():
            shortcut.symlink_to(app, target_is_directory=True)
    return app


def runtime_inventory(prefix):
    records = []
    for path in sorted((prefix/'conda-meta').glob('*.json')):
        entry = json.loads(path.read_text(encoding='utf-8'))
        records.append({key:entry.get(key) for key in ('name','version','build','subdir','url','sha256','license')})
    (prefix/'RUNTIME_PACKAGES.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    licenses = prefix/'THIRD_PARTY_LICENSES'
    licenses.mkdir(exist_ok=True)
    for source in (prefix/'pkgs').glob('*/info/licenses'):
        target = licenses/source.parent.parent.name
        shutil.copytree(source, target, dirs_exist_ok=True)
    return records


def main():
    prefix = Path(sys.prefix)
    payload = prefix/'app_payload'
    wheels = list(payload.glob('*.whl'))
    if len(wheels) != 1:
        raise RuntimeError('Expected exactly one bundled application wheel')
    subprocess.run([sys.executable,'-m','pip','install','--no-index','--no-deps','--no-compile',str(wheels[0])], check=True)
    import mapgis_annotations
    create_app(prefix, mapgis_annotations.__version__)
    packages = runtime_inventory(prefix)
    if not any(record['name']=='qgis' for record in packages):
        raise RuntimeError('QGIS is missing from the offline runtime')


if __name__ == '__main__':
    main()
