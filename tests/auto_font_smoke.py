"""Exercise adaptive sizing through real QGIS, keeping every fixed anchor."""
import json
from pathlib import Path
import sys
import tempfile

import native_fixtures as F
from mapgis_annotations import run_pipeline, verify_dataset


def main():
    with tempfile.TemporaryDirectory(prefix='mapgis-auto-font-') as temporary:
        root = Path(temporary)
        source = root/'input'
        source.mkdir()
        points = [{'x':105+x*.001,'y':35+y*.001,'text':'地质%d' % (x+y*8)}
                  for x in range(8) for y in range(8)]
        points.append({'x':105.1,'y':35.1,'text':''})
        F.write_points(source/'labels.WT', points, proj=0, ellipsoid=7, scale=0)
        result = run_pipeline(source, root/'result', {'render':{'enabled':True,'auto_font_size':True,
                                                            'width_mm':180,'dpi':96,'font_size':9}})
        verify_dataset(root/'result')
        report = json.loads((root/'result/map/export.json').read_text(encoding='utf-8'))
        sizing = report['font_sizing']['labels_点']
        assert report['auto_font_size'] and sizing['applied']
        assert sizing['labels'] == 64 and report['rendered_labels'] == 64
        assert result['audit']['records'] == 65
        assert report['fonts']['probe_glyphs_verified']
        payload = {'status':'PASS','font_sizing':sizing,'records_preserved':65,
                   'rendered_labels':64,'fixed_anchors_verified':True,'source_hashes_verified':True}
        path = Path(sys.argv[1])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(payload, ensure_ascii=False))


if __name__ == '__main__':
    main()
