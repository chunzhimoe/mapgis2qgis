"""Run using the installed PKG's Python, never the build interpreter."""
import json
from pathlib import Path
import sys
import tempfile

import native_fixtures as F
from mapgis_annotations.runtime import configure_runtime
from mapgis_annotations import run_pipeline, verify_dataset


def main():
    configure_runtime()
    import tkinter
    from qgis.core import Qgis
    assert tkinter.Tcl().eval('info patchlevel')
    with tempfile.TemporaryDirectory(prefix='mapgis-installed-smoke-') as temporary:
        root = Path(temporary)
        source = root/'native input'
        source.mkdir()
        F.write_points(source/'labels.WT', [{'x':105,'y':35,'text':'A#-2'}, {'x':105.01,'y':35.01,'text':'地图'}],
                       proj=0,ellipsoid=7,scale=0)
        result = run_pipeline(source,root/'result',{'render':{'enabled':True,'width_mm':180,'dpi':96}})
        verify_dataset(root/'result')
        verify_dataset(root/'result/annotations')
        assert result['map']['rendered_labels']==2
        assert (root/'result/map/map.pdf').stat().st_size>1000
        font_report = json.loads((root/'result/map/export.json').read_text())['fonts']
        assert font_report['probe_glyphs_verified']
        assert (root/'result/map'/font_report['font_file']).is_file()
    report = {'status':'PASS','python':sys.executable,'qgis':Qgis.QGIS_VERSION,
              'native_conversion':True,'annotation_conversion':True,'qgis_rendering':True,'hash_verification':True,
              'font_family':font_report['family'], 'chinese_greek_glyphs_verified':True}
    Path(sys.argv[1]).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
