"""Package the reviewed JSON presets and their instructions for GitHub Release."""
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def package_profiles(output):
    folder = ROOT/'examples/profiles'
    paths = [folder/'README.md', *sorted(folder.glob('*.json'))]
    if not paths[0].is_file() or len(paths) < 2:
        raise RuntimeError('Configuration presets and README are required')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, 'MapGIS2QGIS-profiles/'+path.name)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'dist/MapGIS2QGIS-profiles.zip')
    print(package_profiles(parser.parse_args().output))
