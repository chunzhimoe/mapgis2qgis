"""Compare current native export with a separate 0.2.0 checkout on local maps.

No real inputs or outputs are shipped. Existing georeferenced layers must retain
their coordinates, attributes and CRS; added CRS assignments are reported apart.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from pyproj import CRS


def export(package, source, output):
    env = dict(os.environ, PYTHONPATH=str(package / 'src'))
    result = subprocess.run([sys.executable, '-m', 'mapgis_annotations', 'from-mapgis',
                             str(source), str(output)], env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads((output / 'native_export.json').read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('sources', nargs='+', type=Path)
    args = parser.parse_args()
    current = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    for i, source in enumerate(args.sources):
        old_dir, new_dir = args.output / ('old_%d' % i), args.output / ('new_%d' % i)
        old, new = export(args.baseline, source, old_dir), export(current, source, new_dir)
        assert old['source_sha256'] == new['source_sha256']
        assert old['layers'].keys() == new['layers'].keys()
        checked, added = [], []
        for name, before in old['layers'].items():
            after = new['layers'][name]
            assert before['features'] == after['features'], name
            if before['epsg']:
                assert (before['epsg'], before['factor']) == (after['epsg'], after['factor']), name
                assert CRS((old_dir / (name + '.prj')).read_text()).equals(
                    CRS((new_dir / (name + '.prj')).read_text())), name
                checked.append(name)
            elif after['crs_wkt']:
                added.append(name)
                continue  # expected coordinate changes when a previously unassigned layer gets units/CRS
            for suffix in ('.shp', '.shx', '.dbf', '.cpg'):
                assert (old_dir / (name + suffix)).read_bytes() == (new_dir / (name + suffix)).read_bytes(), (name, suffix)
        cases.append({'source': str(source), 'layers': len(new['layers']),
                      'features': new['summary']['features'], 'existing_crs_preserved': len(checked),
                      'added_crs': added, 'new_summary': new['summary']})
    result = {'status': 'PASS', 'cases': cases}
    (args.output / 'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
