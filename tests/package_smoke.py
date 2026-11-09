"""Check built archives contain current code/docs and no real research data."""
import hashlib
import configparser
import json
from pathlib import Path
import tarfile
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    config = configparser.ConfigParser()
    config.read(root/'setup.cfg')
    version = config['metadata']['version']
    wheel = root/'dist'/('mapgis_annotations-'+version+'-py3-none-any.whl')
    source = root/'dist'/('mapgis_annotations-'+version+'.tar.gz')
    with zipfile.ZipFile(wheel) as bundle:
        assert bundle.testzip() is None
        for path in (root/'src/mapgis_annotations').glob('*.py'):
            assert bundle.read('mapgis_annotations/'+path.name) == path.read_bytes(), path.name
        assert any(name.endswith('/LICENSE') for name in bundle.namelist())
        assert any(name.endswith('/Apache-2.0.txt') for name in bundle.namelist())
        assert any(name.endswith('/THIRD_PARTY_NOTICES.md') for name in bundle.namelist())
        assert bundle.read('mapgis_annotations/profiles/wulonggou_pipeline.json') == (root/'src/mapgis_annotations/profiles/wulonggou_pipeline.json').read_bytes()
        assert not any(name.endswith(('.shp','.dbf','.gpkg','.pdf','.png','.pyc')) for name in bundle.namelist())
    with tarfile.open(source) as bundle:
        names = bundle.getnames()
        for required in ('README.md','LICENSE','THIRD_PARTY_NOTICES.md','licenses/Apache-2.0.txt',
                         'docs/API.md','examples/generic.json','tests/package_smoke.py'):
            assert any(name.endswith('/'+required) for name in names), required
        assert not any('/out/' in name or '/changes/' in name or name.endswith(('.shp','.dbf','.gpkg','.pdf','.png','.pyc')) for name in names)
    result = {'status':'PASS','current_python_modules_match_wheel':True,'source_docs_examples_present':True,
              'research_data_in_archives':False,
              'artifacts':{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                           for p in (wheel, source)}}
    (root/'out').mkdir(exist_ok=True)
    (root/'out/package_validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
