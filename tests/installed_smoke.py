"""Run this file with the installed distribution's interpreter from /tmp."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import mapgis_annotations as package
from mapgis_annotations import parse_note


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    assert 'site-packages' in package.__file__, package.__file__
    assert 'qgis' not in sys.modules and 'shapely' not in sys.modules
    assert parse_note('ηγT#-2').unicode == 'ηγT₂'
    command = Path(sys.executable).parent/'mapgis-annotations'
    success = subprocess.run([str(command),'parse','A#-2'], check=True, capture_output=True, text=True)
    assert json.loads(success.stdout)['unicode'] == 'A₂'
    failure = subprocess.run([str(command),'parse','A#?2','--strict'], capture_output=True, text=True)
    assert failure.returncode == 2 and 'Unknown MapGIS' in failure.stderr
    result = {'status':'PASS','installed_module':package.__file__,'outside_project':str(Path.cwd()),
              'console_script':str(command),'optional_gis_not_imported':True}
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
