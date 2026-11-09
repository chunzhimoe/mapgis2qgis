"""Exercise shipped generic presets with real native data, QGIS and PDF output."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import native_fixtures as F
from mapgis_annotations import verify_dataset

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = []
    with tempfile.TemporaryDirectory(prefix='mapgis-profiles-smoke-') as temporary:
        root = Path(temporary)
        source, partial = root/'native', root/'with unreadable'
        source.mkdir()
        partial.mkdir()
        F.write_points(source/'labels.WT', [{'x':105,'y':35,'text':'ηγT#-2'},
                                            {'x':105.01,'y':35.01,'text':'中文注记'}],
                       proj=0, ellipsoid=7, scale=0)
        shutil.copyfile(source/'labels.WT', partial/'labels.WT')
        (partial/'bad.WT').write_bytes(b'broken')
        for profile in sorted((ROOT/'examples/profiles').glob('*.json')):
            if profile.name.startswith('06_'):
                continue  # This region-specific preset needs the real map; test separately.
            config = json.loads(profile.read_text(encoding='utf-8'))
            data = source if config['strict_native'] else partial
            if config['input_format'] == 'shp':
                data = root/'01_generic_full_pdf/native'
            output = root/profile.stem
            result = subprocess.run([sys.executable,'-m','mapgis_annotations','pipeline',str(data),
                                     str(output),'--config',str(profile)], capture_output=True, text=True,
                                    encoding='utf-8', timeout=180)
            assert result.returncode == 0, (profile.name, result.stdout, result.stderr)
            verify_dataset(output)
            manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
            assert manifest['audit']['records'] == 2
            assert (output/'map/map.pdf').exists() == config['render']['enabled']
            if config['render']['enabled']:
                for name in ('map.pdf','map.png','map.qgz','preview.png'):
                    assert (output/'map'/name).stat().st_size > 100
                assert manifest['map']['rendered_labels'] == 2
                fonts = json.loads((output/'map/export.json').read_text())['fonts']
                assert fonts['probe_glyphs_verified']
            if config['input_format'] != 'shp':
                assert manifest['native_summary']['unreadable'] == (0 if config['strict_native'] else 1)
            report.append({'profile':profile.name,'status':'PASS','pdf':config['render']['enabled'],
                           'source_hashes_verified':True,'records':2,
                           'font_glyphs_verified':bool(config['render']['enabled'])})
        strict = ROOT/'examples/profiles/02_strict_full_pdf.json'
        refused = root/'strict-refused'
        result = subprocess.run([sys.executable,'-m','mapgis_annotations','pipeline',str(partial),
                                 str(refused),'--config',str(strict)], capture_output=True, text=True,
                                encoding='utf-8', timeout=60)
        assert result.returncode != 0 and 'unreadable' in result.stderr and not refused.exists()
    payload = {'status':'PASS','profiles':report,'strict_failure_rolled_back':True}
    path = Path(sys.argv[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == '__main__':
    main()
